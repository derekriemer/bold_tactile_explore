"""Relief: is the printed terrain tall enough to feel, and short enough to print?"""

from __future__ import annotations

import numpy as np

from tactile_terrain.analyzers.base import (
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    Z_STEP,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
    round_to,
)
from tactile_terrain.registry import analyzers


class Relief:
    """Printed relief against the minimum needed to feel it, and the printer height."""

    name = "relief"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        if ctx.spec.mode == "flat" or ctx.hf.terrain_z is None:
            return AnalyzerResult()
        t = ctx.hf.transform
        relief = ctx.hf.terrain_z - t.base_mm
        maximum = float(relief.max())
        low, high = np.percentile(relief, [PERCENTILE_LOW, PERCENTILE_HIGH])
        spread = float(high - low)
        total_height = t.base_mm + maximum
        bed_height = ctx.printer.bed_mm[2]
        metrics = {
            "max_relief_mm": maximum,
            "relief_spread_mm": spread,
            "total_height_mm": total_height,
            "z_exaggeration": t.z_exaggeration,
        }
        out = AnalyzerResult(metrics)
        current = t.z_exaggeration

        if total_height > bed_height:
            allowed = (bed_height - t.base_mm) / maximum * current
            suggested = float(max(Z_STEP, np.floor(allowed / Z_STEP) * Z_STEP))
            out.suggestions.append(
                Suggestion(
                    "error",
                    f"Total height is {total_height:.1f} mm, taller than the {bed_height:g} mm "
                    f"the printer can build. Setting z exaggeration to {suggested:g} fits.",
                    {"print": {"z_exaggeration": suggested}},
                )
            )
            return out

        if 0 < spread < ctx.profile.min_relief_mm:
            wanted = round_to(current * ctx.profile.target_relief_mm / spread, Z_STEP)
            cap = np.floor((bed_height - t.base_mm) / maximum * current / Z_STEP) * Z_STEP
            suggested = float(min(wanted, cap))
            new_spread = spread * suggested / current
            capped = " (limited by the printer height)" if suggested < wanted else ""
            out.suggestions.append(
                Suggestion(
                    "warn",
                    f"Printed relief is {spread:.1f} mm (98th minus 2nd percentile), below the "
                    f"{ctx.profile.min_relief_mm:g} mm needed to feel it. Setting z exaggeration "
                    f"to {suggested:g}{capped} gives {new_spread:.1f} mm of relief and "
                    f"{t.base_mm + maximum * suggested / current:.1f} mm total height.",
                    {"print": {"z_exaggeration": suggested}},
                )
            )
        return out


analyzers.register("relief", Relief())
