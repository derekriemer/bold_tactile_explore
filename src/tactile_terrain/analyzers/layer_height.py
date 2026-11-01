"""Line heights against the printer's layer height: how many layers each style prints as."""

from __future__ import annotations

from tactile_terrain.analyzers.base import (
    EPS,
    ROUND_DIGITS,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
)
from tactile_terrain.layers import layer_count, snap_up
from tactile_terrain.registry import analyzers


class LayerHeight:
    """Reports how each line style in use prints in whole layers. Heights snap up, never down."""

    name = "layer_height"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        layer = ctx.printer.layer_height_mm
        out = AnalyzerResult()
        if layer <= 0:
            out.metrics = {"layer_height_mm": None}
            return out
        floor_h = ctx.profile.min_line_height_mm
        per_style = {}
        for style_name in sorted({f.style for f in ctx.spec.features}):
            asked = ctx.profile.lines[style_name].height_mm
            printed = snap_up(asked, layer)
            layers = layer_count(asked, layer)
            per_style[style_name] = {"asked_mm": asked, "printed_mm": printed, "layers": layers}
            if printed > asked + EPS:
                out.suggestions.append(
                    Suggestion(
                        "info",
                        f"Line style {style_name} is {asked:g} mm tall, which is not a whole "
                        f"number of {layer:g} mm layers. It prints as {layers} layers, "
                        f"{printed:g} mm.",
                    )
                )
            # Fewer printed layers than the profile minimum needs is a sign the line is faint.
            needed = layer_count(floor_h, layer)
            if layers < needed:
                raised = round(needed * layer, ROUND_DIGITS)
                out.suggestions.append(
                    Suggestion(
                        "warn",
                        f"Line style {style_name} prints as {layers} layers, fewer than the "
                        f"{needed} layers the {floor_h:g} mm minimum height needs.",
                        {"style": {"overrides": {"lines": {style_name: {"height_mm": raised}}}}},
                    )
                )
        out.metrics = {"layer_height_mm": layer, "styles": per_style}
        return out


analyzers.register("layer_height", LayerHeight())
