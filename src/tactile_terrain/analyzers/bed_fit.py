"""Does the print fit the printer bed?"""

from __future__ import annotations

import math

from tactile_terrain.analyzers.base import (
    EPS,
    SCALE_STEP,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
)
from tactile_terrain.registry import analyzers


class BedFit:
    """Footprint and height against the usable printer bed."""

    name = "bed_fit"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        hf, printer = ctx.hf, ctx.printer
        ny, nx = hf.z.shape
        width, depth = (nx - 1) * hf.grid_mm, (ny - 1) * hf.grid_mm
        height = float(hf.z.max())
        bed_x, bed_y, bed_z = printer.bed_mm
        usable_x = bed_x - 2 * printer.bed_margin_mm
        usable_y = bed_y - 2 * printer.bed_margin_mm
        out = AnalyzerResult(
            {
                "footprint_mm": [width, depth],
                "height_mm": height,
                "usable_bed_mm": [usable_x, usable_y, bed_z],
            }
        )
        fits_xy = (width <= usable_x and depth <= usable_y) or (
            width <= usable_y and depth <= usable_x
        )
        if fits_xy and height <= bed_z:
            return out

        t = hf.transform
        shrink = min(
            max(width / usable_x, depth / usable_y), max(width / usable_y, depth / usable_x)
        )
        rise = height - t.base_mm
        if rise > 0 and bed_z > t.base_mm:
            shrink = max(shrink, rise / (bed_z - t.base_mm))
        suggested = float(SCALE_STEP * math.ceil(t.scale_m_per_mm * shrink / SCALE_STEP - EPS))
        patch: dict = {"print": {"scale_m_per_mm": suggested}}
        if ctx.spec.print.long_side_mm is not None:
            patch["print"]["long_side_mm"] = None
        out.suggestions.append(
            Suggestion(
                "error",
                f"The print is {width:.1f} mm by {depth:.1f} mm and {height:.1f} mm tall, but "
                f"the usable bed is {usable_x:g} mm by {usable_y:g} mm by {bed_z:g} mm "
                f"(after a {printer.bed_margin_mm:g} mm margin). A scale of {suggested:g} m "
                "per mm fits.",
                patch,
            )
        )
        return out


analyzers.register("bed_fit", BedFit())
