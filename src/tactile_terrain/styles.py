"""Line styles: cross-section functions h(d), the raised height at distance d from a centreline.

Widths and heights always come from the resolved tactile profile entry (invariant 1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tactile_terrain.registry import line_styles
from tactile_terrain.tactile.profile import TactileProfile, apply_overrides

# Printability geometry, not a tactile threshold: see the spec's line feature table.
FLAT_TOP_SHOULDER_DEG = 60


def rounded(d: np.ndarray, width: float, height: float) -> np.ndarray:
    """Half-ellipse: h * sqrt(1 - (2d/w)^2)."""
    u = np.clip(2 * np.asarray(d, dtype=float) / width, 0, 1)
    return height * np.sqrt(1 - u**2)


def flat_top(d: np.ndarray, width: float, height: float) -> np.ndarray:
    """Central plateau with straight shoulders at 60 degrees, reaching zero at w/2."""
    half = width / 2
    run = min(height / np.tan(np.radians(FLAT_TOP_SHOULDER_DEG)), half)
    return height * np.clip((half - np.asarray(d, dtype=float)) / run, 0, 1)


def pointed(d: np.ndarray, width: float, height: float) -> np.ndarray:
    """Triangle: h * (1 - 2d/w). Flanks are 45 degrees or steeper when h >= w/2."""
    return height * np.clip(1 - 2 * np.asarray(d, dtype=float) / width, 0, 1)


line_styles.register("rounded", rounded)
line_styles.register("flat_top", flat_top)
line_styles.register("pointed", pointed)


@dataclass(frozen=True)
class LineStyle:
    name: str  # key in the profile's [lines] table, e.g. "rounded_major"
    profile: str  # cross-section shape: "rounded" | "flat_top" | "pointed"
    width_mm: float
    height_mm: float

    def h(self, d: np.ndarray) -> np.ndarray:
        return line_styles.get(self.profile)(d, self.width_mm, self.height_mm)


def resolve_style(name: str, profile: TactileProfile, overrides: dict | None = None) -> LineStyle:
    lines = apply_overrides(profile, overrides or {}).lines
    if name not in lines:
        raise KeyError(f"Unknown line style '{name}'. Valid names: {', '.join(sorted(lines))}")
    entry = lines[name]
    return LineStyle(name, entry.profile, entry.width_mm, entry.height_mm)
