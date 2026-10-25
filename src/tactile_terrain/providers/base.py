"""Provider interfaces and the data types shared by the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from rasterio.transform import Affine
from shapely.geometry.base import BaseGeometry

BBox = tuple[float, float, float, float]  # west, south, east, north (degrees)


@dataclass(frozen=True)
class SourceInfo:
    """What attribution.py needs to credit a data source."""

    name: str
    licence: str
    attribution: str


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


@dataclass
class LineFeature:
    geometry: BaseGeometry  # WGS84 lon/lat
    name: str
    kind: str  # provider-specific class, e.g. "stream", "primary", "chair_lift"
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class NamedPoint:
    """A named peak, pass or saddle. Used for naming in text only; never printed."""

    name: str
    kind: str  # "peak" | "pass" | "saddle"
    lon: float
    lat: float
    elevation_m: float | None = None


class ElevationProvider(Protocol):
    source: SourceInfo

    def fetch(self, bbox: BBox, resolution_m: float) -> ElevationGrid:
        """Return elevations covering the lon/lat bbox."""
        ...


class LineProvider(Protocol):
    source: SourceInfo

    def fetch(self, bbox: BBox, feature_type: str, filter: dict[str, Any]) -> list[LineFeature]:
        """Return the lines of `feature_type` inside the bbox that pass `filter`."""
        ...


class PointProvider(Protocol):
    def fetch_points(self, bbox: BBox) -> list[NamedPoint]: ...


class AreaProvider(Protocol):
    """Polygon features (water, land). No implementations in Phase 1."""

    source: SourceInfo

    def fetch_areas(self, bbox: BBox, feature_type: str, filter: dict[str, Any]) -> list[Any]: ...
