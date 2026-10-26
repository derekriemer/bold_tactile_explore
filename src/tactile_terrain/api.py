"""The functions that do the work. server.py and cli.py are thin wrappers around these."""

from __future__ import annotations

import contextlib
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
from tactile_terrain.geo import lonlat_transformer, projected_bounds, utm_crs_for
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
    refs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in roads:
        by_class[r.kind].append(r.name)
        for ref in filter(None, (p.strip() for p in r.attrs["ref"].split(";"))):
            refs[r.kind][ref].add(r.name or "unnamed")
    lines.append(f"Roads (motorway through tertiary): {len(roads)} segments.")
    for kind in sorted(by_class):
        ref_text = (
            ", ".join(
                f"{ref} = {' / '.join(sorted(names))}" for ref, names in sorted(refs[kind].items())
            )
            or "none"
        )
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
MAX_LISTED_OUT = 15


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
    spec_path = model_dir / "spec.json"
    before = spec_path.read_bytes() if spec_path.exists() else None
    model_dir.mkdir(parents=True, exist_ok=True)
    save_spec(spec, spec_path)
    start = time.perf_counter()
    try:
        result = run_pipeline(
            spec, model_dir, cfg.printer(spec.print.printer), on_stage=on_progress
        )
        write_attribution(spec, model_dir / "ATTRIBUTION.txt")
        _save_description(spec.name, model_dir)
    except BaseException:
        # A failed build must not leave a model behind that blocks the retry: put the old spec
        # back, or remove the new one. Downloaded data in cache/ stays, so the retry is quick.
        if before is None:
            spec_path.unlink(missing_ok=True)
        else:
            spec_path.write_bytes(before)
        raise
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
    _refuse_sampler(spec, "analyze_model")
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


def _save_description(name: str, model_dir) -> None:
    """Keep DESCRIPTION.md, the default text description, next to the model."""
    (model_dir / "DESCRIPTION.md").write_text(describe_model(name), encoding="utf-8")


def describe_model(name: str, sections: list[dict] | None = None, brief: bool = False) -> str:
    """The text description of a built model. `sections` adds extra cross-sections. `brief`
    gives only the overview, warnings, legend and distortion."""
    from tactile_terrain.describe import DescribeInput, describe

    cfg = load_config()
    model_dir = cfg.models_path / name
    spec_path = model_dir / "spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"No model named {name} in {cfg.models_path}.")
    spec = load_spec(spec_path)
    if spec.kind == "sampler":
        from tactile_terrain.describe import describe_sampler
        from tactile_terrain.sampler import build_plate

        plate = build_plate(spec, cfg.printer(spec.print.printer))
        paths = {
            "Folder": str(model_dir),
            "STL file": str(model_dir / f"{name}.stl"),
            "Spec file": str(spec_path),
        }
        return describe_sampler(plate, spec, paths, cfg.describe)
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
    if brief:
        return describe(m, brief_warnings=_analysis_text(spec, result, cfg))
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
    _refuse_sampler(current, "update_model")
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


def _lengths_m(features, crs: str) -> dict[tuple[str, str], float]:
    """Ground length in metres of each (name, kind), summed over its segments."""
    import shapely

    transformer = lonlat_transformer(crs)

    def length(geometry) -> float:
        def convert(coords):
            x, y = transformer.transform(coords[:, 0], coords[:, 1])
            return np.column_stack([x, y])

        return float(shapely.transform(geometry, convert).length)

    totals: dict[tuple[str, str], float] = defaultdict(float)
    for f in features:
        totals[(f.name or "unnamed", f.kind)] += length(f.geometry)
    return totals


def _line_list(totals, limit: int | None = None) -> str:
    ranked = sorted(totals.items(), key=lambda item: -item[1])
    shown = ranked if limit is None else ranked[:limit]
    text = "; ".join(
        f"{name} ({kind}, {metres / METRES_PER_KM:.1f} km)" for (name, kind), metres in shown
    )
    more = len(ranked) - len(shown)
    return text + (f"; and {more} more" if more > 0 else "") if text else "none"


def preview_features(
    features: list[dict] | None = None, name: str | None = None, bbox: list[float] | None = None
) -> str:
    """Dry run of feature filters: what each would keep and leave out. Changes nothing."""
    cache = None
    if name is not None:
        model_dir = _model_dir(name)
        cache = model_dir / "cache"
        spec = load_spec(model_dir / "spec.json")
        bbox = bbox or list(spec.area.bbox)
        features = features if features is not None else [f.model_dump() for f in spec.features]
    if not bbox or not features:
        raise ValueError("Give a bbox, or the name of a model, and the features to preview.")
    with using_cache_dir(cache) if cache else contextlib.nullcontext():
        return _preview(features, tuple(float(v) for v in bbox))


def _preview(features: list[dict], area: tuple[float, ...]) -> str:
    crs = utm_crs_for(area)
    lines = [f"Preview of {len(features)} features over {area}. Nothing was built or changed."]
    for feature in features:
        provider = line_providers.get(feature["provider"])
        kept = _lengths_m(provider.fetch(area, feature["type"], feature.get("filter", {})), crs)
        everything = _lengths_m(provider.fetch(area, feature["type"], {}), crs)
        left_out = {key: metres for key, metres in everything.items() if key not in kept}
        lines += [
            "",
            f"{feature['type']} ({feature['provider']}, filter {json.dumps(feature.get('filter', {}))}):",
            f"  Keeps {len(kept)} lines: {_line_list(kept)}.",
            (
                f"  Leaves out {len(left_out)} of the {len(everything)} the service has: "
                f"{_line_list(left_out, MAX_LISTED_OUT)}."
            ),
        ]
    return "\n".join(lines)


def model_history(name: str) -> str:
    """Every saved version of a model's spec, oldest first, with what changed between them."""
    model_dir = _model_dir(name)
    numbers = backup_numbers(model_dir)
    if not numbers:
        return f"Model {name} has no earlier versions; it has not been edited."
    states = [
        (f"Version {n}", json.loads((model_dir / f"spec.{n}.json").read_text(encoding="utf-8")))
        for n in numbers
    ]
    states.append(("Current", json.loads((model_dir / "spec.json").read_text(encoding="utf-8"))))
    lines = [
        f"History of model {name}, oldest first.",
        (
            'To go back, call update_model with {"revert_to": N}, or {"revert_to": "last"} to undo '
            "the latest edit. Going back keeps the state you leave as a new version, so it can be undone."
        ),
    ]
    previous = None
    for label, state in states:
        if previous is None:
            lines.append(f"{label}: the first spec.")
        else:
            changed = diff_lines(previous, state)
            lines.append(f"{label}: " + ("same as the version before." if not changed else ""))
            lines += [f"  {c}" for c in changed]
        previous = state
    return "\n".join(lines)


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
        if spec.kind == "sampler":
            lines.append(f"  {model}: sampler plate, {spec.style.tactile_profile} profile.")
            continue
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
    if spec.kind == "sampler":
        return _check_sampler(name, spec, model_dir, printer)
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
    what = (
        f"a tactile relief map. Terrain is raised from a flat base and rivers, roads and lifts "
        f"are raised lines. 1 mm = {t.scale_m_per_mm:g} m horizontally, with vertical "
        f"exaggeration {t.z_exaggeration:g} times."
    )
    notes = printpack.print_notes(name, what, report, printer)
    _save_description(name, model_dir)
    written = printpack.write_print_pack(
        model_dir,
        stl,
        model_dir / "ATTRIBUTION.txt",
        notes,
        printpack.submit_notes(printer),
    )
    files = ", ".join(p.name for p in written)
    return f"{text}\nPrint pack written to {model_dir / 'print-pack'}: {files}."


# --- sampler plates ------------------------------------------------------------------------

SAMPLER_SEED_LIMIT = 1_000_000


def _refuse_sampler(spec_or_dict, action: str) -> None:
    kind = spec_or_dict.get("kind") if isinstance(spec_or_dict, dict) else spec_or_dict.kind
    if kind == "sampler":
        raise ValueError(
            f"A sampler plate cannot be used with {action}. Create a new plate with "
            "create_sampler instead."
        )


def create_sampler(
    profile: str | None = None,
    focus: str | None = None,
    seed: int | None = None,
    name: str | None = None,
    printer: str | None = None,
    overwrite: bool = False,
) -> str:
    """Build a single-round calibration plate around a tactile profile's current values.

    focus limits the plate to one row type: profiles, widths, heights or spacing.
    """
    import random

    from tactile_terrain.export.stl import export_stl
    from tactile_terrain.mesh import mesh_within_size
    from tactile_terrain.sampler import build_plate

    cfg = load_config()
    profile_name = profile or cfg.active_profile
    load_profile(profile_name)  # an unknown name lists the valid ones
    printer_name = printer or cfg.default_printer
    machine = cfg.printer(printer_name)
    seed = seed if seed is not None else random.SystemRandom().randrange(1, SAMPLER_SEED_LIMIT)
    name = name or "-".join(["sampler", profile_name, *([focus] if focus else [])])
    spec = Spec.model_validate(
        {
            "name": name,
            "mode": "flat",
            "area": {"bbox": [0, 0, 0.001, 0.001]},  # unused: a plate has no map area
            "print": {"printer": printer_name, "scale_m_per_mm": 1, "base_mm": 3.0},
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
            "style": {"tactile_profile": profile_name},
            "kind": "sampler",
            "sampler": {"focus": focus, "seed": seed},
        }
    )
    plate = build_plate(spec, machine)
    spec = spec.model_copy(
        update={
            "sampler": spec.sampler.model_copy(update={"sample_length_mm": plate.sample_length_mm})
        }
    )
    model_dir = cfg.models_path / name
    if (model_dir / "spec.json").exists() and not overwrite:
        raise FileExistsError(f"Model {name} already exists in {model_dir}. Use overwrite.")
    model_dir.mkdir(parents=True, exist_ok=True)
    save_spec(spec, model_dir / "spec.json")
    mesh, _ = mesh_within_size(plate.z, plate.grid_mm, machine.max_stl_mb)
    stl = export_stl(mesh, model_dir / f"{name}.stl")
    (model_dir / "ATTRIBUTION.txt").write_text(
        f"Attribution for the sampler plate {name}\n\n"
        "No map data is used. Generated with tactile-terrain.\n",
        encoding="utf-8",
    )
    _save_description(name, model_dir)
    shortened = (
        f" Samples were shortened from {plate.requested_length_mm:g} mm to "
        f"{plate.sample_length_mm:g} mm to fit."
        if plate.sample_length_mm < plate.requested_length_mm
        else ""
    )
    return "\n".join(
        [
            f"Built sampler plate {name} with the {profile_name} tactile profile.",
            f"Folder: {model_dir}",
            f"STL: {stl} ({stl.stat().st_size / BYTES_PER_MB:.1f} MB).",
            (
                f"Plate: {plate.width_mm:.1f} mm by {plate.height_mm:.1f} mm, {plate.base_mm:g} mm "
                f"base, {len(plate.rows)} rows, {len(plate.cells)} numbered samples.{shortened}"
            ),
            (
                "Use describe_model for the row-by-row readout. Feel the plate first: the readout "
                "reveals which pairs are identical."
            ),
        ]
    )


def _check_sampler(name: str, spec: Spec, model_dir, printer) -> str:
    import numpy as np
    import trimesh

    from tactile_terrain import printpack
    from tactile_terrain.sampler import build_plate

    plate = build_plate(spec, printer)
    stl = model_dir / f"{name}.stl"
    report = printpack.mesh_report(trimesh.load(stl, force="mesh", process=True), printer)
    steepest = float(np.degrees(np.arctan(np.hypot(*np.gradient(plate.z, plate.grid_mm)).max())))
    usable_x = printer.bed_mm[0] - 2 * printer.bed_margin_mm
    usable_y = printer.bed_mm[1] - 2 * printer.bed_margin_mm
    printability = []
    if plate.width_mm > usable_x or plate.height_mm > usable_y:
        printability.append("The plate is larger than the usable bed.")
    size_line = f"STL size {stl.stat().st_size / BYTES_PER_MB:.1f} MB."
    text = printpack.check_text(
        name, report, printer, None, None, "", printability, steepest, size_line
    )
    what = (
        "a tactile calibration plate. It has rows of paired, widening and closely spaced raised "
        "lines, each with a numeral, so a person can find which differences they can feel."
    )
    notes = printpack.print_notes(name, what, report, printer)
    _save_description(name, model_dir)
    written = printpack.write_print_pack(
        model_dir, stl, model_dir / "ATTRIBUTION.txt", notes, printpack.submit_notes(printer)
    )
    files = ", ".join(p.name for p in written)
    return f"{text}\nPrint pack written to {model_dir / 'print-pack'}: {files}."
