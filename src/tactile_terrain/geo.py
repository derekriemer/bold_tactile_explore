"""Projection and the world <-> print coordinate transform.

Print coordinates (spec "Print coordinates"): millimetres, origin at the south-west corner,
x east, y north, z up from the bottom of the base. "World" means UTM metres.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from pyproj import Transformer

BBox = tuple[float, float, float, float]  # west, south, east, north (degrees)
UTM_ZONE_WIDTH_DEG = 6  # geodetic constant, not a tactile number


def utm_crs_for(bbox: BBox) -> str:
    west, south, east, north = bbox
    lon, lat = (west + east) / 2, (south + north) / 2
    zone = int((lon + 180) // UTM_ZONE_WIDTH_DEG) + 1
    base = 32600 if lat >= 0 else 32700
    return f"EPSG:{base + zone}"


def lonlat_transformer(crs: str) -> Transformer:
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)


def projected_bounds(bbox: BBox, crs: str) -> tuple[float, float, float, float]:
    """Bounding rectangle (xmin, ymin, xmax, ymax) of the lon/lat bbox in `crs`."""
    west, south, east, north = bbox
    t = lonlat_transformer(crs)
    xs, ys = t.transform([west, east, west, east], [south, south, north, north])
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


@dataclass(frozen=True)
class PrintTransform:
    crs: str
    sw_x: float  # metres
    sw_y: float
    width_m: float
    height_m: float
    scale_m_per_mm: float
    z_exaggeration: float
    base_mm: float
    min_elevation_m: float

    @classmethod
    def build(
        cls,
        bbox: BBox,
        *,
        scale_m_per_mm: float | None = None,
        long_side_mm: float | None = None,
        z_exaggeration: float = 1.0,
        base_mm: float = 0.0,
        min_elevation_m: float = 0.0,
        crs: str | None = None,
    ) -> PrintTransform:
        crs = crs or utm_crs_for(bbox)
        xmin, ymin, xmax, ymax = projected_bounds(bbox, crs)
        width_m, height_m = xmax - xmin, ymax - ymin
        if scale_m_per_mm is None:
            if long_side_mm is None:
                raise ValueError("Give scale_m_per_mm or long_side_mm")
            scale_m_per_mm = max(width_m, height_m) / long_side_mm
        return cls(
            crs=crs,
            sw_x=xmin,
            sw_y=ymin,
            width_m=width_m,
            height_m=height_m,
            scale_m_per_mm=scale_m_per_mm,
            z_exaggeration=z_exaggeration,
            base_mm=base_mm,
            min_elevation_m=min_elevation_m,
        )

    @property
    def width_mm(self) -> float:
        return self.width_m / self.scale_m_per_mm

    @property
    def height_mm(self) -> float:
        return self.height_m / self.scale_m_per_mm

    def with_min_elevation(self, min_elevation_m: float) -> PrintTransform:
        return replace(self, min_elevation_m=float(min_elevation_m))

    def world_to_print(self, x, y):
        return (
            (np.asarray(x) - self.sw_x) / self.scale_m_per_mm,
            (np.asarray(y) - self.sw_y) / self.scale_m_per_mm,
        )

    def print_to_world(self, px, py):
        return (
            np.asarray(px) * self.scale_m_per_mm + self.sw_x,
            np.asarray(py) * self.scale_m_per_mm + self.sw_y,
        )

    def elevation_to_z(self, e):
        rise_mm = (np.asarray(e) - self.min_elevation_m) / self.scale_m_per_mm
        return self.base_mm + rise_mm * self.z_exaggeration

    def z_to_elevation(self, z):
        rise_mm = (np.asarray(z) - self.base_mm) / self.z_exaggeration
        return rise_mm * self.scale_m_per_mm + self.min_elevation_m
