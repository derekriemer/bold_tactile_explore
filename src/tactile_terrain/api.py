"""The functions that do the work. server.py and cli.py are thin wrappers around these."""

from __future__ import annotations

import math
import time
from collections import defaultdict

import numpy as np

from tactile_terrain import providers  # noqa: F401  (registers the built-in providers)
from tactile_terrain.attribution import write_attribution
from tactile_terrain.config import load_config
from tactile_terrain.geo import projected_bounds, utm_crs_for
from tactile_terrain.pipeline.stages import run_pipeline
from tactile_terrain.providers import nominatim
from tactile_terrain.providers.base import BBox
from tactile_terrain.providers.usgs3dep import available_resolutions
from tactile_terrain.registry import elevation_providers, line_providers
from tactile_terrain.spec import Spec, save_spec, validate_registry_names

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


def build_spec(spec: Spec, overwrite: bool = False) -> str:
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
    result = run_pipeline(spec, model_dir, cfg.printer(spec.print.printer))
    write_attribution(spec, model_dir / "ATTRIBUTION.txt")
    return _summary(spec, result, time.perf_counter() - start, model_dir)


def create_model(
    name: str,
    area: dict | list,
    print: dict,
    mode: str = "terrain",
    features: list[dict] | None = None,
    style: dict | None = None,
    elevation: dict | None = None,
    overwrite: bool = False,
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
    return build_spec(spec, overwrite=overwrite)
