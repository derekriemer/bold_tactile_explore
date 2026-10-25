"""Minimum width and height of every line style in use."""

from __future__ import annotations

from tactile_terrain.analyzers.base import (
    NOZZLE_WIDTH_FACTOR,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
)
from tactile_terrain.registry import analyzers


class MinWidth:
    """Line styles in use against the minimum printable width and height."""

    name = "min_width"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        floor_w = max(ctx.profile.min_line_width_mm, NOZZLE_WIDTH_FACTOR * ctx.printer.nozzle_mm)
        floor_h = ctx.profile.min_line_height_mm
        used = sorted({f.style for f in ctx.spec.features})
        out = AnalyzerResult()
        narrowest = None
        for style_name in used:
            entry = ctx.profile.lines[style_name]
            narrowest = entry.width_mm if narrowest is None else min(narrowest, entry.width_mm)
            changes: dict[str, float] = {}
            problems = []
            if entry.width_mm < floor_w:
                changes["width_mm"] = floor_w
                problems.append(f"{entry.width_mm:g} mm wide, below the {floor_w:g} mm minimum")
            if entry.height_mm < floor_h:
                changes["height_mm"] = floor_h
                problems.append(f"{entry.height_mm:g} mm tall, below the {floor_h:g} mm minimum")
            if not problems:
                continue
            new_w = changes.get("width_mm", entry.width_mm)
            new_h = changes.get("height_mm", entry.height_mm)
            if entry.profile == "pointed" and new_h < new_w / 2:
                changes["height_mm"] = new_w / 2  # keep flanks at 45 degrees or steeper
            out.suggestions.append(
                Suggestion(
                    "warn",
                    f"Line style {style_name} is {' and '.join(problems)}.",
                    {"style": {"overrides": {"lines": {style_name: changes}}}},
                )
            )
        out.metrics = {"narrowest_line_mm": narrowest, "min_width_floor_mm": floor_w}
        return out


analyzers.register("min_width", MinWidth())
