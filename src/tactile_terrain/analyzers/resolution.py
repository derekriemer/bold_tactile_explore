"""Resolution: source elevation detail compared with the print grid."""

from __future__ import annotations

from tactile_terrain.analyzers.base import AnalysisContext, AnalyzerResult, Suggestion
from tactile_terrain.registry import analyzers


class Resolution:
    """Source elevation cell size against the print grid."""

    name = "resolution"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        if ctx.source_resolution_m is None:
            return AnalyzerResult()
        source = ctx.source_resolution_m
        cell = ctx.hf.grid_mm * ctx.hf.transform.scale_m_per_mm
        out = AnalyzerResult({"source_cell_m": source, "print_cell_ground_m": cell})
        if source < cell:
            out.suggestions.append(
                Suggestion(
                    "info",
                    f"Elevation data has {source:g} m cells, but each print grid cell covers "
                    f"{cell:g} m of ground, so detail finer than {cell:g} m is averaged away.",
                )
            )
        elif source > cell:
            out.suggestions.append(
                Suggestion(
                    "info",
                    f"Elevation data has {source:g} m cells, coarser than the {cell:g} m of "
                    f"ground per print grid cell, so the surface is interpolated and features "
                    f"smaller than {source:g} m are not real detail.",
                )
            )
        return out


analyzers.register("resolution", Resolution())
