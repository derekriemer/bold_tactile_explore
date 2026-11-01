"""Layer height: raised features can only print in whole layers, so heights snap up to them."""

from __future__ import annotations

import math
from dataclasses import replace

from tactile_terrain.styles import LineStyle

EPS = 1e-9  # numerical tolerance when a height is already a whole number of layers
ROUND_DIGITS = 6


def snap_up(height_mm: float, layer_mm: float) -> float:
    """The smallest whole number of layers that is at least `height_mm`.

    Always rounds up, never down, so a feature never drops below the height the profile asked for.
    A layer height of 0 means unknown, and the height is returned unchanged.
    """
    if layer_mm <= 0:
        return height_mm
    return round(math.ceil(height_mm / layer_mm - EPS) * layer_mm, ROUND_DIGITS)


def layer_count(height_mm: float, layer_mm: float) -> int:
    """Whole layers a feature of this height prints as (after snapping up)."""
    return round(snap_up(height_mm, layer_mm) / layer_mm)


def snap_style(style: LineStyle, layer_mm: float) -> LineStyle:
    return replace(style, height_mm=snap_up(style.height_mm, layer_mm))
