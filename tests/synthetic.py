"""Synthetic elevation grids with analytically known heights.

Each builder returns an ElevationGrid (array plus georeferencing). Cell (row, col) has its
centre at x = x0 + (col + 0.5) * res, y = y0 - (row + 0.5) * res.
"""

from __future__ import annotations

import numpy as np

from tactile_terrain.providers.base import ElevationGrid


def _make(fn, n: int, res: float, crs: str, x0: float, y0: float) -> ElevationGrid:
    xs = x0 + (np.arange(n) + 0.5) * res
    ys = y0 - (np.arange(n) + 0.5) * res
    x, y = np.meshgrid(xs, ys)
    return ElevationGrid(fn(x, y), crs, x0, y0, res, res)


def plane(elevation=1000.0, slope_x=0.0, slope_y=0.0, n=50, res=10.0,
          crs="EPSG:32613", x0=0.0, y0=0.0) -> ElevationGrid:  # fmt: skip
    """z = elevation + slope_x * (x - x0) + slope_y * (y - y0)."""
    return _make(lambda x, y: elevation + slope_x * (x - x0) + slope_y * (y - y0),
                 n, res, crs, x0, y0)  # fmt: skip


def cone(peak_m=500.0, radius_m=400.0, base_m=1000.0, n=101, res=10.0,
         crs="EPSG:32613", x0=0.0, y0=0.0) -> ElevationGrid:  # fmt: skip
    """A cone centred on the grid: z = base + peak * max(0, 1 - r / radius)."""
    cx, cy = x0 + n * res / 2, y0 - n * res / 2

    def fn(x, y):
        r = np.hypot(x - cx, y - cy)
        return base_m + peak_m * np.maximum(0.0, 1 - r / radius_m)

    return _make(fn, n, res, crs, x0, y0)


def valley(depth_m=100.0, half_width_m=200.0, rim_m=1000.0, n=101, res=10.0,
           crs="EPSG:32613", x0=0.0, y0=0.0) -> ElevationGrid:  # fmt: skip
    """A V-shaped valley running north-south: z = rim - depth * max(0, 1 - |x - cx| / hw)."""
    cx = x0 + n * res / 2

    def fn(x, y):
        return rim_m - depth_m * np.maximum(0.0, 1 - np.abs(x - cx) / half_width_m)

    return _make(fn, n, res, crs, x0, y0)
