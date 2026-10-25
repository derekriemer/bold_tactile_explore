"""USGS 3DEP elevation through py3dep."""

from __future__ import annotations

import math

import numpy as np
import rasterio

from tactile_terrain.providers.base import BBox, ElevationGrid, SourceInfo
from tactile_terrain.providers.cache import cache_path, read_json, write_json
from tactile_terrain.registry import elevation_providers

METRES_PER_DEGREE = 111_000.0
PAD_CELLS = 3  # margin so the reprojected footprint stays inside the data


def _write_tif(path, grid: ElevationGrid) -> None:
    ny, nx = grid.data.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=ny, width=nx, count=1, dtype="float32",
        crs=grid.crs, transform=grid.affine, nodata=float("nan"), compress="deflate",
    ) as ds:  # fmt: skip
        ds.write(grid.data.astype("float32"), 1)


def _read_tif(path) -> ElevationGrid:
    with rasterio.open(path) as ds:
        a = ds.transform
        return ElevationGrid(ds.read(1).astype(float), ds.crs.to_string(), a.c, a.f, a.a, -a.e)


def available_resolutions(bbox: BBox) -> list[str]:
    """3DEP resolutions with coverage for the bbox, finest first (for example '1m', '10m')."""
    path = cache_path("usgs3dep-availability", bbox, "json")
    data = read_json(path)
    if data is None:
        import py3dep

        data = py3dep.check_3dep_availability(bbox)
        write_json(path, data)
    found = [k for k, v in data.items() if v and k[:-1].isdigit() and k.endswith("m")]
    return sorted(found, key=lambda k: int(k[:-1]))


class Usgs3dep:
    source = SourceInfo(
        name="USGS 3D Elevation Program (3DEP)",
        licence="Public domain",
        attribution="Elevation data: U.S. Geological Survey, 3D Elevation Program (3DEP).",
    )

    def fetch(self, bbox: BBox, resolution_m: float) -> ElevationGrid:
        path = cache_path("usgs3dep", bbox, "tif", resolution_m=float(resolution_m))
        if path.exists():
            return _read_tif(path)
        grid = self._download(bbox, resolution_m)
        _write_tif(path, grid)
        return grid

    def _download(self, bbox: BBox, resolution_m: float) -> ElevationGrid:
        import py3dep

        west, south, east, north = bbox
        pad_lat = PAD_CELLS * resolution_m / METRES_PER_DEGREE
        pad_lon = pad_lat / max(math.cos(math.radians((south + north) / 2)), 1e-3)
        padded = (west - pad_lon, south - pad_lat, east + pad_lon, north + pad_lat)
        dem = py3dep.get_dem(padded, resolution_m)
        a = dem.rio.transform()
        data = np.asarray(dem.values, dtype=float)
        return ElevationGrid(data, dem.rio.crs.to_string(), a.c, a.f, a.a, -a.e)


elevation_providers.register("usgs3dep", Usgs3dep())
