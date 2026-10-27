"""Parallel spacing: different lines running closer together than a finger can separate."""

from __future__ import annotations

import math

from shapely.geometry import MultiLineString, Point

from tactile_terrain.analyzers.base import (
    WORST_PLACES_REPORTED,
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
)
from tactile_terrain.registry import analyzers


def _label(line) -> str:
    return line.name or f"unnamed {line.feature_type}"


METRES_STEP = 5  # suggested merge distances are rounded up to a multiple of this
MERGE_MARGIN = 1.25  # and given this much room beyond the measured gap


def _vertices(piece):
    return [Point(c) for c in piece.coords]


class Spacing:
    """Different lines running closer together than the profile allows."""

    name = "spacing"

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult:
        gap_min = ctx.profile.min_parallel_spacing_mm
        min_run = ctx.profile.min_feature_length_mm
        lines = ctx.hf.lines
        found = []
        for i, a in enumerate(lines):
            for b in lines[i + 1 :]:
                if a.name and a.name == b.name:
                    continue  # one named feature drawn in two styles
                if a.feature_type == b.feature_type and a.geometry.intersects(b.geometry):
                    continue  # pieces of one feature joined end to end, not a close parallel
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
        out.suggestions += _divided(ctx, gap_min)
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


def _divided(ctx: AnalysisContext, gap_min: float) -> list[Suggestion]:
    """Pieces of one named road running side by side: a divided road drawn twice."""
    scale = ctx.hf.transform.scale_m_per_mm
    out = []
    for line in ctx.hf.lines:
        if not isinstance(line.geometry, MultiLineString) or not line.name:
            continue
        reach = line.style.width_mm + gap_min
        parts = sorted(line.geometry.geoms, key=lambda p: -p.length)
        worst = None
        for i, a in enumerate(parts):
            for b in parts[i + 1 :]:
                if a.distance(b) >= reach:
                    continue
                near = b.intersection(a.buffer(reach))
                for piece in getattr(near, "geoms", [near]):
                    if piece.geom_type != "LineString" or piece.length <= 2 * reach:
                        continue
                    gap = max(a.distance(v) for v in _vertices(piece))
                    if worst is None or piece.length > worst[0]:
                        worst = (piece.length, gap, piece.interpolate(piece.length / 2))
        if worst is None:
            continue
        length, gap, centre = worst
        metres = math.ceil(gap * scale * MERGE_MARGIN / METRES_STEP) * METRES_STEP
        patch = _merge_patch(ctx, line.feature_type, metres)
        out.append(
            Suggestion(
                "warn",
                f"{_label(line)} has two pieces running side by side, up to {gap:.1f} mm apart "
                f"for {length:.1f} mm near x = {centre.x:.0f} mm, y = {centre.y:.0f} mm. A "
                "divided road feels like one doubled ridge. Merging pieces of the same name "
                f"within {metres} m keeps one.",
                patch,
            )
        )
    return out


def _merge_patch(ctx: AnalysisContext, feature_type: str, metres: int) -> dict | None:
    features = [f.model_dump(mode="json") for f in ctx.spec.features]
    for feature in features:
        if feature["type"] == feature_type:
            feature["filter"] = {**feature.get("filter", {}), "merge_within_m": metres}
            return {"features": features}
    return None


analyzers.register("spacing", Spacing())
