"""The functions that do the work. server.py and cli.py are thin wrappers around these."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from collections import defaultdict

import numpy as np
from pyproj import CRS

from tactile_terrain import providers  # noqa: F401  (registers the built-in providers)
from tactile_terrain.analyzers import AnalysisContext, format_analysis, run_all
from tactile_terrain.attribution import write_attribution
from tactile_terrain.config import load_config
from tactile_terrain.editing import apply_changes, backup_numbers, diff_lines
from tactile_terrain.geo import projected_bounds, utm_crs_for
from tactile_terrain.pipeline.stages import run_pipeline
from tactile_terrain.providers import nominatim
from tactile_terrain.providers.base import BBox
from tactile_terrain.providers.cache import using_cache_dir
from tactile_terrain.providers.usgs3dep import available_resolutions
from tactile_terrain.registry import elevation_providers, line_providers
from tactile_terrain.spec import Spec, load_spec, save_spec, validate_registry_names
from tactile_terrain.tactile.profile import apply_overrides, load_profile

COARSE_RESOLUTION_M = 90
METRES_PER_KM = 1000


def _square_around(lon: float, lat: float, width_km: float) -> BBox:
    half_lat = width_km / 2 / 110.57
    half_lon = width_km / 2 / (111.32 * math.cos(math.radians(lat)))
    return (lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat)


def _name_list(names: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for n in names:
        if n:
            counts[n] += 1
    return ", ".join(sorted(counts)) if counts else "none named"


def resolve_area(
    place: str | None = None,
    bbox: BBox | list[float] | None = None,
    width_km: float | None = None,
) -> str:
    """Describe an area in plain text: size, elevation range, and what features it holds."""
    lines: list[str] = []
    if bbox is None:
        if not place:
            raise ValueError("Give a place name or a bbox [west, south, east, north].")
        found = nominatim.geocode(place)
        lines.append(f"Place: {found.display_name}")
        bbox = _square_around(found.lon, found.lat, width_km) if width_km else found.bbox
    west, south, east, north = (float(v) for v in bbox)
    bbox = (west, south, east, north)

    crs = utm_crs_for(bbox)
    xmin, ymin, xmax, ymax = projected_bounds(bbox, crs)
    lines += [
        (
            f"Bounding box: west {west:.5f}, south {south:.5f}, east {east:.5f}, north {north:.5f} "
            "degrees."
        ),
        (
            f"Size: {(xmax - xmin) / METRES_PER_KM:.1f} km east-west by "
            f"{(ymax - ymin) / METRES_PER_KM:.1f} km north-south."
        ),
        f"Projection: UTM, {crs}.",
    ]

    grid = elevation_providers.get("usgs3dep").fetch(bbox, COARSE_RESOLUTION_M)
    lines.append(
        f"Elevation range (from a {COARSE_RESOLUTION_M} m sample): "
        f"{np.nanmin(grid.data):.0f} m to {np.nanmax(grid.data):.0f} m."
    )
    lines.append(
        "Available 3DEP resolutions: " + (", ".join(available_resolutions(bbox)) or "none") + "."
    )

    streams = line_providers.get("nhd").fetch(bbox, "river", {})
    by_order: dict[int, list[str]] = defaultdict(list)
    for s in streams:
        by_order[s.attrs["stream_order"]].append(s.name)
    lines.append(f"Streams: {len(streams)} segments.")
    for order in sorted(by_order, reverse=True):
        lines.append(
            f"  Stream order {order}: {len(by_order[order])} segments; "
            f"names: {_name_list(by_order[order])}."
        )

    osm = line_providers.get("osm")
    roads = osm.fetch(bbox, "road", {})
    by_class: dict[str, list[str]] = defaultdict(list)
    refs: dict[str, set[str]] = defaultdict(set)
    for r in roads:
        by_class[r.kind].append(r.name)
        if r.attrs["ref"]:
            refs[r.kind].add(r.attrs["ref"])
    lines.append(f"Roads (motorway through tertiary): {len(roads)} segments.")
    for kind in sorted(by_class):
        ref_text = ", ".join(sorted(refs[kind])) or "none"
        lines.append(
            f"  {kind}: {len(by_class[kind])} segments; refs: {ref_text}; "
            f"names: {_name_list(by_class[kind])}."
        )

    lifts = osm.fetch(bbox, "lift", {"aerialway": "all"})
    by_type: dict[str, list[str]] = defaultdict(list)
    for lift in lifts:
        by_type[lift.kind].append(lift.name)
    lines.append(f"Aerialways: {len(lifts)}.")
    for kind in sorted(by_type):
        lines.append(f"  {kind}: {len(by_type[kind])}; names: {_name_list(by_type[kind])}.")

    points = osm.fetch_points(bbox)
    lines.append(f"Named peaks, passes and saddles: {len(points)}.")
    for p in sorted(points, key=lambda p: (p.kind, p.name)):
        elevation = f", {p.elevation_m:.0f} m" if p.elevation_m is not None else ""
        lines.append(f"  {p.kind}: {p.name}{elevation} (lon {p.lon:.4f}, lat {p.lat:.4f}).")

    return "\n".join(lines)


# --- building ------------------------------------------------------------------------------

MM_PER_M = 1000
BYTES_PER_MB = 1_000_000
MAX_DROPPED_LISTED = 10


def _summary(spec: Spec, result: dict, seconds: float, model_dir) -> str:
    hf = result["lines"]
    exported = result["export"]
    ny, nx = hf.z.shape
    t = hf.transform
    terrain_top = float(hf.terrain_z.max())
    size_mb = exported.path.stat().st_size / BYTES_PER_MB
    lines = [
        f"Built model '{spec.name}' in {seconds:.1f} seconds.",
        f"Folder: {model_dir}",
        f"STL: {exported.path} ({size_mb:.1f} MB, {exported.n_faces} triangles).",
        (
            f"Footprint: {(nx - 1) * hf.grid_mm:.1f} mm east-west by "
            f"{(ny - 1) * hf.grid_mm:.1f} mm north-south, mode {spec.mode}."
        ),
        (
            f"Height: base {t.base_mm:.1f} mm, terrain top {terrain_top:.1f} mm, "
            f"highest point with lines {float(hf.z.max()):.1f} mm."
        ),
        (
            f"Scale: 1 mm = {t.scale_m_per_mm:g} m horizontally; vertical exaggeration "
            f"{t.z_exaggeration:g} times. Grid cell {hf.grid_mm:g} mm."
        ),
    ]
    if spec.mode == "terrain":
        lines.append(
            f"Terrain elevation from {t.min_elevation_m:.0f} m to "
            f"{float(t.z_to_elevation(terrain_top)):.0f} m."
        )
    for feature in spec.features:
        kept = [x for x in hf.lines if x.feature_type == feature.type]
        lines.append(
            f"Lines, {feature.type} ({feature.style}): {len(kept)} named or unnamed lines kept."
        )
    if hf.dropped:
        shown = ", ".join(
            f"{d.name or 'unnamed'} {d.feature_type} {d.length_mm:.1f} mm"
            for d in hf.dropped[:MAX_DROPPED_LISTED]
        )
        more = len(hf.dropped) - MAX_DROPPED_LISTED
        lines.append(
            f"Dropped {len(hf.dropped)} pieces as too short to feel: {shown}"
            + (f", and {more} more." if more > 0 else ".")
        )
    return "\n".join(lines)


def build_spec(spec: Spec, overwrite: bool = False, on_progress=None) -> str:
    """Write the spec, run the pipeline, write the STL and attribution. Returns a summary."""
    cfg = load_config()
    validate_registry_names(spec, cfg)
    model_dir = cfg.models_path / spec.name
    if (model_dir / "spec.json").exists() and not overwrite:
        raise FileExistsError(
            f"Model '{spec.name}' already exists in {model_dir}. "
            "Use overwrite, or change it with update_model."
        )
    model_dir.mkdir(parents=True, exist_ok=True)
    save_spec(spec, model_dir / "spec.json")
    start = time.perf_counter()
    result = run_pipeline(spec, model_dir, cfg.printer(spec.print.printer), on_stage=on_progress)
    write_attribution(spec, model_dir / "ATTRIBUTION.txt")
    summary = _summary(spec, result, time.perf_counter() - start, model_dir)
    return "\n\n".join([summary, "Analysis:", _analysis_text(spec, result, cfg)])


def create_model(
    name: str,
    area: dict | list,
    print: dict,
    mode: str = "terrain",
    features: list[dict] | None = None,
    style: dict | None = None,
    elevation: dict | None = None,
    overwrite: bool = False,
    on_progress=None,
) -> str:
    """Create a model from plain arguments. `area` is {"bbox": [...]} or just the bbox list."""
    cfg = load_config()
    spec = Spec.model_validate(
        {
            "name": name,
            "mode": mode,
            "area": {"bbox": area} if isinstance(area, list) else area,
            "print": {"printer": cfg.default_printer} | print,
            "elevation": elevation or {"provider": "usgs3dep", "resolution_m": 10},
            "features": features or [],
            "style": style or {"tactile_profile": cfg.active_profile},
        }
    )
    return build_spec(spec, overwrite=overwrite, on_progress=on_progress)


def _source_resolution_m(spec: Spec, result: dict) -> float | None:
    grid = result["fetch"]
    if grid is None:
        return None
    if CRS.from_user_input(grid.crs).is_geographic:  # cell size in degrees: use the requested size
        return float(spec.elevation.resolution_m)
    return float(min(grid.dx, grid.dy))


def _analysis_context(spec: Spec, result: dict, cfg) -> AnalysisContext:
    return AnalysisContext(
        spec=spec,
        profile=apply_overrides(load_profile(spec.style.tactile_profile), spec.style.overrides),
        printer=cfg.printer(spec.print.printer),
        hf=result["lines"],
        source_resolution_m=_source_resolution_m(spec, result),
    )


def _analysis_text(spec: Spec, result: dict, cfg) -> str:
    return format_analysis(run_all(_analysis_context(spec, result, cfg)))


def analyze_model(name: str) -> str:
    """Metrics and suggestions for a built model: warnings first, each with its fix."""
    cfg = load_config()
    model_dir = cfg.models_path / name
    spec_path = model_dir / "spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"No model named {name} in {cfg.models_path}.")
    spec = load_spec(spec_path)
    result = run_pipeline(spec, model_dir, cfg.printer(spec.print.printer))
    return "\n".join([f"Analysis of model {name}:", _analysis_text(spec, result, cfg)])


def _print_points(spec: Spec, hf, model_dir) -> list:
    """Named peaks and passes from OSM, placed in print mm and kept if inside the footprint."""
    from tactile_terrain.describe import PrintPoint
    from tactile_terrain.geo import lonlat_transformer

    if not any(f.provider == "osm" for f in spec.features):
        return []
    west, south, east, north = (float(v) for v in spec.area.bbox)
    with using_cache_dir(model_dir / "cache"):
        points = line_providers.get("osm").fetch_points((west, south, east, north))
    to_world = lonlat_transformer(hf.transform.crs)
    ny, nx = hf.z.shape
    width, depth = (nx - 1) * hf.grid_mm, (ny - 1) * hf.grid_mm
    placed = []
    for p in points:
        x, y = (float(v) for v in hf.transform.world_to_print(*to_world.transform(p.lon, p.lat)))
        if 0 <= x <= width and 0 <= y <= depth:
            placed.append(PrintPoint(p.name, p.kind, x, y, p.elevation_m))
    return placed


def describe_model(name: str, sections: list[dict] | None = None) -> str:
    """The full text description of a built model. `sections` adds extra cross-sections."""
    from tactile_terrain.describe import DescribeInput, describe

    cfg = load_config()
    model_dir = cfg.models_path / name
    spec_path = model_dir / "spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"No model named {name} in {cfg.models_path}.")
    spec = load_spec(spec_path)
    result = run_pipeline(spec, model_dir, cfg.printer(spec.print.printer))
    hf = result["lines"]
    m = DescribeInput(
        spec=spec,
        profile=apply_overrides(load_profile(spec.style.tactile_profile), spec.style.overrides),
        printer=cfg.printer(spec.print.printer),
        hf=hf,
        settings=cfg.describe.model_copy(),
        points=_print_points(spec, hf, model_dir),
        paths={
            "Folder": str(model_dir),
            "STL file": str(result["export"].path),
            "Spec file": str(spec_path),
            "Attribution file": str(model_dir / "ATTRIBUTION.txt"),
        },
        source_resolution_m=_source_resolution_m(spec, result),
    )
    return describe(m, sections)


# --- editing and discovery -------------------------------------------------------------------


def _model_dir(name: str):
    cfg = load_config()
    model_dir = cfg.models_path / name
    if not (model_dir / "spec.json").exists():
        known = ", ".join(_model_names(cfg)) or "none yet"
        raise FileNotFoundError(f"No model named {name} in {cfg.models_path}. Models: {known}.")
    return model_dir


def _model_names(cfg) -> list[str]:
    root = cfg.models_path
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "spec.json").exists())


def update_model(name: str, changes: dict, on_progress=None) -> str:
    """Apply a merge-patch and shortcuts to a model's spec, rebuild, and report before -> after.

    Shortcuts: z_multiply, crop_percent, drop_feature, revert_to. The previous spec is kept
    as spec.<n>.json. An invalid change leaves the spec untouched.
    """
    model_dir = _model_dir(name)
    spec_path = model_dir / "spec.json"
    current = json.loads(spec_path.read_text(encoding="utf-8"))
    new = apply_changes(current, changes, model_dir)
    try:
        spec = Spec.model_validate(new)
        validate_registry_names(spec)
    except (ValueError, KeyError) as error:
        raise ValueError(f"Change rejected, the spec is unchanged. {error}") from error
    if spec.name != name:
        raise ValueError("A model cannot be renamed; create a new model instead.")
    changed = diff_lines(current, json.loads(spec.model_dump_json()))
    if not changed:
        return f"No change: model {name} already has those settings."
    number = max(backup_numbers(model_dir), default=0) + 1
    backup = model_dir / f"spec.{number}.json"
    shutil.copy2(spec_path, backup)
    summary = build_spec(spec, overwrite=True, on_progress=on_progress)
    lines = ["Changes:", *[f"  {c}" for c in changed], f"Previous spec kept as {backup.name}."]
    return "\n".join(lines) + "\n\n" + summary


def list_models() -> str:
    cfg = load_config()
    names = _model_names(cfg)
    if not names:
        return f"No models yet in {cfg.models_path}."
    lines = [f"Models in {cfg.models_path}:"]
    for model in names:
        spec = load_spec(cfg.models_path / model / "spec.json")
        versions = len(backup_numbers(cfg.models_path / model))
        scale = spec.print.scale_m_per_mm
        size = f"1 mm = {scale:g} m" if scale else f"{spec.print.long_side_mm:g} mm long side"
        lines.append(
            f"  {model}: {spec.mode}, {size}, {len(spec.features)} feature types, "
            f"{versions} earlier versions."
        )
    return "\n".join(lines)


def get_spec(name: str) -> str:
    return (_model_dir(name) / "spec.json").read_text(encoding="utf-8")


def list_capabilities() -> str:
    from tactile_terrain.capabilities import list_capabilities as capabilities

    return capabilities(load_config())


def doctor() -> str:
    """An environment report: versions, config, models folder, data services, slicer."""
    from tactile_terrain.doctor import run_doctor

    return run_doctor(load_config())


def check_print(name: str) -> str:
    """Check the model is printable, estimate filament and time, and write the print pack."""
    import numpy as np
    import trimesh

    from tactile_terrain import printpack

    cfg = load_config()
    model_dir = _model_dir(name)
    spec = load_spec(model_dir / "spec.json")
    printer = cfg.printer(spec.print.printer)
    result = run_pipeline(spec, model_dir, printer)
    stl = result["export"].path
    mesh = trimesh.load(stl, force="mesh", process=True)
    report = printpack.mesh_report(mesh, printer)

    hf = result["lines"]
    gradient = np.hypot(*np.gradient(hf.z, hf.grid_mm))
    steepest = float(np.degrees(np.arctan(gradient.max())))

    ctx = _analysis_context(spec, result, cfg)
    found = run_all(ctx)
    printability = [s.message for key in ("min_width", "bed_fit") for s in found[key].suggestions]

    slicer = printpack.find_slicer()
    sliced, note = None, ""
    if slicer and printer.slicer_config:
        try:
            sliced = printpack.run_slicer(slicer, printer.slicer_config, stl)
        except (OSError, subprocess.SubprocessError) as error:
            note = f"Slicing with {slicer} failed: {error}."
    elif slicer:
        note = f"Found {slicer}, but this printer has no slicer_config in the user config."

    exported = result["export"]
    if exported.decimated_tolerance_mm is None:
        size_line = f"STL size {exported.size_mb:.1f} MB."
    else:
        size_line = (
            f"STL size {exported.size_mb:.1f} MB, flat areas thinned (tolerance "
            f"{exported.decimated_tolerance_mm:g} mm) to stay under {printer.max_stl_mb:g} MB."
        )
    text = printpack.check_text(
        name, report, printer, slicer, sliced, note, printability, steepest, size_line
    )

    t = hf.transform
    notes = printpack.print_notes(name, t.scale_m_per_mm, t.z_exaggeration, report, printer)
    written = printpack.write_print_pack(
        model_dir,
        stl,
        model_dir / "ATTRIBUTION.txt",
        notes,
        printpack.submit_notes(printer),
    )
    files = ", ".join(p.name for p in written)
    return f"{text}\nPrint pack written to {model_dir / 'print-pack'}: {files}."
