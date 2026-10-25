"""Provider interfaces and the raster type shared by the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from rasterio.transform import Affine


@dataclass
class ElevationGrid:
    """Elevations in metres on a regular grid. Row 0 is the north edge."""

    data: np.ndarray
    crs: str
    x0: float  # west edge, in CRS units
    y0: float  # north edge, in CRS units
    dx: float  # cell width, positive
    dy: float  # cell height, positive

    @property
    def affine(self) -> Affine:
        return Affine(self.dx, 0, self.x0, 0, -self.dy, self.y0)


class ElevationProvider(Protocol):
    def fetch(self, bbox: tuple[float, float, float, float], resolution_m: float) -> ElevationGrid:
        """Return elevations covering the lon/lat bbox (west, south, east, north)."""
        ...
