"""Compose line features onto the heightfield.

surface = terrain + max over features of h_f(d_f), where d_f is the distance to feature f.
Where features overlap the taller profile wins. No booleans, so the mesh stays watertight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, box

from tactile_terrain.styles import LineStyle
from tactile_terrain.tactile.profile import TactileProfile

# Performance tuning (vertices per distance chunk), not a tactile number.
CHUNK_VERTICES = 8


@dataclass
class PlacedLine:
    name: str
    feature_type: str
    style: LineStyle
    geometry: LineString | MultiLineString  # print mm


@dataclass
class Dropped:
    name: str
    feature_type: str
    length_mm: float


@dataclass
class ComposeResult:
    surface: np.ndarray
    lines: list[PlacedLine]
    dropped: list[Dropped]


def _parts(geometry) -> list[LineString]:
    merged = shapely.line_merge(geometry) if geometry.geom_type != "LineString" else geometry
    if merged.is_empty:
        return []
    if merged.geom_type == "LineString":
        return [merged]
    return [
        g for g in getattr(merged, "geoms", []) if g.geom_type == "LineString" and not g.is_empty
    ]


def prepare(
    lines: list[PlacedLine], footprint: tuple[float, float], profile: TactileProfile
) -> tuple[list[PlacedLine], list[Dropped]]:
    """Clip to the print footprint, simplify, and drop pieces shorter than the profile allows."""
    area = box(0, 0, *footprint)
    kept, dropped = [], []
    for line in lines:
        pieces = []
        for part in _parts(shapely.intersection(line.geometry, area)):
            part = part.simplify(profile.simplify_mm, preserve_topology=True)
            if part.length < profile.min_feature_length_mm:
                dropped.append(Dropped(line.name, line.feature_type, part.length))
            else:
                pieces.append(part)
        if pieces:
            kept.append(replace(line, geometry=MultiLineString(pieces)))
    return kept, dropped


def _chunks(line: LineString):
    coords = list(line.coords)
    step = CHUNK_VERTICES - 1
    for start in range(0, len(coords) - 1, step):
        yield LineString(coords[start : start + step + 1])


def raise_lines(terrain: np.ndarray, grid_mm: float, lines: list[PlacedLine]) -> np.ndarray:
    """Return terrain plus the tallest feature profile at every grid point."""
    ny, nx = terrain.shape
    raised = np.zeros_like(terrain, dtype=float)
    for placed in lines:
        reach = placed.style.width_mm / 2
        for part in placed.geometry.geoms:
            for chunk in _chunks(part):
                minx, miny, maxx, maxy = chunk.bounds
                i0 = max(0, math.ceil((minx - reach) / grid_mm))
                i1 = min(nx - 1, math.floor((maxx + reach) / grid_mm))
                j0 = max(0, math.ceil((miny - reach) / grid_mm))
                j1 = min(ny - 1, math.floor((maxy + reach) / grid_mm))
                if i0 > i1 or j0 > j1:
                    continue
                xs, ys = np.meshgrid(
                    np.arange(i0, i1 + 1) * grid_mm, np.arange(j0, j1 + 1) * grid_mm
                )
                d = shapely.distance(shapely.points(xs, ys), chunk)
                window = raised[j0 : j1 + 1, i0 : i1 + 1]
                np.maximum(window, placed.style.h(d), out=window)
    return terrain + raised


def compose(
    terrain: np.ndarray,
    grid_mm: float,
    lines: list[PlacedLine],
    profile: TactileProfile,
) -> ComposeResult:
    ny, nx = terrain.shape
    kept, dropped = prepare(lines, ((nx - 1) * grid_mm, (ny - 1) * grid_mm), profile)
    return ComposeResult(raise_lines(terrain, grid_mm, kept), kept, dropped)
