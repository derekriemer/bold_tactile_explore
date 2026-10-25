"""The build pipeline: fetch -> project -> warp -> heightfield -> texture -> lines -> base ->
tile -> export. Each stage is a pure function of the spec slice it reads plus the previous
stage's output, and its result is cached."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy import ndimage

import tactile_terrain.export.stl
import tactile_terrain.warp  # noqa: F401  (registers the identity warp)
from tactile_terrain.config import PrinterProfile
from tactile_terrain.geo import PrintTransform, utm_crs_for
from tactile_terrain.mesh import heightfield_to_mesh
from tactile_terrain.pipeline.cache import StageCache, stage_key
from tactile_terrain.providers.base import ElevationGrid
from tactile_terrain.registry import elevation_providers, exporters
from tactile_terrain.spec import Spec
from tactile_terrain.tactile.profile import load_profile

EPS = 1e-9  # numerical tolerance when counting grid cells


@dataclass
class Context:
    model_dir: Path
    printer: PrinterProfile


@dataclass
class Heightfield:
    z: np.ndarray  # (ny, nx), mm; row 0 is y = 0 (south)
    grid_mm: float
    transform: PrintTransform


@dataclass
class ExportResult:
    path: Path
    n_vertices: int
    n_faces: int
    bounds_mm: list[list[float]]


def _bbox(spec: Spec) -> tuple[float, float, float, float]:
    west, south, east, north = spec.area.bbox
    return float(west), float(south), float(east), float(north)


def _crs(spec: Spec) -> str:
    return utm_crs_for(_bbox(spec)) if spec.area.crs == "auto" else spec.area.crs


# --- stages -------------------------------------------------------------------------------


def fetch(spec: Spec, upstream: Any, ctx: Context) -> ElevationGrid | None:
    if spec.mode == "flat":
        return None
    provider = elevation_providers.get(spec.elevation.provider)
    return provider.fetch(_bbox(spec), float(spec.elevation.resolution_m))


def project(spec: Spec, grid: ElevationGrid | None, ctx: Context) -> ElevationGrid | None:
    if grid is None or grid.crs == _crs(spec):
        return grid
    target = _crs(spec)
    ny, nx = grid.data.shape
    left, top = grid.x0, grid.y0
    right, bottom = left + nx * grid.dx, top - ny * grid.dy
    affine, width, height = calculate_default_transform(
        grid.crs, target, nx, ny, left, bottom, right, top
    )
    out = np.full((height, width), np.nan)
    reproject(
        grid.data.astype(float),
        out,
        src_transform=grid.affine,
        src_crs=grid.crs,
        dst_transform=affine,
        dst_crs=target,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return ElevationGrid(out, target, affine.c, affine.f, affine.a, -affine.e)


def warp(spec: Spec, upstream: Any, ctx: Context) -> Any:
    return upstream  # identity until Phase 2


def _fill_nan(data: np.ndarray) -> np.ndarray:
    mask = np.isnan(data)
    if not mask.any():
        return data
    if mask.all():
        raise ValueError("Elevation data covers none of the requested area")
    nearest = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return data[tuple(nearest)]


def heightfield(spec: Spec, grid: ElevationGrid | None, ctx: Context) -> Heightfield:
    p = spec.print
    transform = PrintTransform.build(
        _bbox(spec),
        scale_m_per_mm=p.scale_m_per_mm,
        long_side_mm=p.long_side_mm,
        z_exaggeration=float(p.z_exaggeration),
        base_mm=float(p.base_mm),
        crs=_crs(spec),
    )
    g = ctx.printer.grid_mm
    nx = int(transform.width_mm / g + EPS) + 1
    ny = int(transform.height_mm / g + EPS) + 1
    if grid is None:  # flat mode: terrain is base_mm everywhere
        return Heightfield(np.full((ny, nx), transform.base_mm), g, transform)

    # Vertex positions in world metres, then in source pixel coordinates.
    px, py = np.meshgrid(np.arange(nx) * g, np.arange(ny) * g)
    wx, wy = transform.print_to_world(px, py)
    cols = (wx - grid.x0) / grid.dx - 0.5
    rows = (grid.y0 - wy) / grid.dy - 0.5
    data = _fill_nan(np.asarray(grid.data, dtype=float))
    cell_m = g * transform.scale_m_per_mm
    factor = cell_m / min(grid.dx, grid.dy)
    if factor > 1:  # source finer than the print grid: average over the cell
        data = ndimage.uniform_filter(data, size=round(factor), mode="nearest")
    elevation = ndimage.map_coordinates(data, [rows, cols], order=1, mode="nearest")
    transform = transform.with_min_elevation(elevation.min())
    return Heightfield(transform.elevation_to_z(elevation), g, transform)


def texture(spec: Spec, upstream: Any, ctx: Context) -> Any:
    return upstream  # no textures until Phase 2


def lines(spec: Spec, hf: Heightfield, ctx: Context) -> Heightfield:
    return hf  # line features arrive in M4


def base(spec: Spec, hf: Heightfield, ctx: Context) -> Heightfield:
    return hf  # the base is part of the heightfield (z starts at base_mm)


def tile(spec: Spec, upstream: Any, ctx: Context) -> Any:
    return upstream  # no tiling until Phase 2


def export(spec: Spec, hf: Heightfield, ctx: Context) -> ExportResult:
    mesh = heightfield_to_mesh(hf.z, hf.grid_mm)
    path = exporters.get("stl")(mesh, ctx.model_dir / f"{spec.name}.stl")
    return ExportResult(path, len(mesh.vertices), len(mesh.faces), mesh.bounds.tolist())


# --- stage table --------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    name: str
    func: Callable[[Spec, Any, Context], Any]
    spec_slice: Callable[[Spec, Context], Any]
    valid: Callable[[Any], bool] = lambda result: True


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


STAGES: list[Stage] = [
    Stage("fetch", fetch, lambda s, c: [s.mode, _dump(s.area), _dump(s.elevation)]),
    Stage("project", project, lambda s, c: _crs(s)),
    Stage("warp", warp, lambda s, c: s.regions),
    Stage("heightfield", heightfield, lambda s, c: [_dump(s.print), c.printer.grid_mm]),
    Stage("texture", texture, lambda s, c: s.textures),
    Stage(
        "lines",
        lines,
        lambda s, c: [
            [_dump(f) for f in s.features],
            s.style.overrides,
            _dump(load_profile(s.style.tactile_profile)),
        ],
    ),
    Stage("base", base, lambda s, c: s.print.base_mm),
    Stage("tile", tile, lambda s, c: s.tiles),
    Stage("export", export, lambda s, c: s.name, valid=lambda r: Path(r.path).exists()),
]


def run_pipeline(
    spec: Spec,
    model_dir: Path,
    printer: PrinterProfile,
    stages: list[Stage] | None = None,
) -> dict[str, Any]:
    """Run every stage in order, reusing cached results. Returns {stage name: result}."""
    ctx = Context(Path(model_dir), printer)
    cache = StageCache(ctx.model_dir)
    results: dict[str, Any] = {}
    key, upstream = "", None
    for stage in stages or STAGES:
        key = stage_key(stage.name, stage.spec_slice(spec, ctx), key)
        hit, result = cache.load(stage.name, key)
        if not (hit and stage.valid(result)):
            result = stage.func(spec, upstream, ctx)
            cache.store(stage.name, key, result)
        results[stage.name] = upstream = result
    return results


__all__ = ["STAGES", "Context", "ExportResult", "Heightfield", "Stage", "run_pipeline"]
