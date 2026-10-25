"""Horizontal warps. Phase 1 ships only the identity warp."""

from __future__ import annotations

from typing import Protocol

from tactile_terrain.providers.base import ElevationGrid
from tactile_terrain.registry import warps


class Warp(Protocol):
    def apply(self, grid: ElevationGrid) -> ElevationGrid:
        """Return the warped grid. Real warps must also report their distortion ratios."""
        ...


class IdentityWarp:
    def apply(self, grid: ElevationGrid) -> ElevationGrid:
        return grid


warps.register("identity", IdentityWarp())
