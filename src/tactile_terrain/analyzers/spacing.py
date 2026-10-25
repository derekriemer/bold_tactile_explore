"""Parallel spacing: different lines running closer together than a finger can separate."""

from __future__ import annotations

from tactile_terrain.analyzers.base import (
    WORST_PLACES_REPORTED,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
)
from tactile_terrain.registry import analyzers


def _label(line) -> str:
    return line.name or f"unnamed {line.feature_type}"


class Spacing:
    name = "spacing"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        gap_min = ctx.profile.min_parallel_spacing_mm
        min_run = ctx.profile.min_feature_length_mm
        lines = ctx.hf.lines
        found = []
        for i, a in enumerate(lines):
            for b in lines[i + 1 :]:
                half_widths = a.style.width_mm / 2 + b.style.width_mm / 2
                reach = half_widths + gap_min
                if a.geometry.distance(b.geometry) >= reach:
                    continue
                near = a.geometry.intersection(b.geometry.buffer(reach))
                for piece in getattr(near, "geoms", [near]):
                    if piece.geom_type != "LineString" or piece.length <= min_run:
                        continue
                    centre = piece.interpolate(piece.length / 2)
                    edge_gap = b.geometry.distance(piece) - half_widths
                    found.append((edge_gap, piece.length, centre.x, centre.y, a, b))
        found.sort(key=lambda f: (f[0], -f[1]))
        out = AnalyzerResult({"close_parallel_places": len(found), "places": found})
        for edge_gap, length, x, y, a, b in found[:WORST_PLACES_REPORTED]:
            out.suggestions.append(
                Suggestion(
                    "warn",
                    f"{_label(a)} and {_label(b)} run {max(edge_gap, 0):.1f} mm apart "
                    f"(edge to edge) for {length:.1f} mm near x = {x:.0f} mm, y = {y:.0f} mm; "
                    f"they need {gap_min:g} mm to stay separate under the finger.",
                )
            )
        return out


analyzers.register("spacing", Spacing())
