"""Importing this package registers the built-in analyzers."""

from tactile_terrain.analyzers import bed_fit, min_width, relief, resolution, spacing  # noqa: F401
from tactile_terrain.analyzers.base import (
    AnalysisContext,
    AnalyzerResult,
    Suggestion,
    describe_patch,
)
from tactile_terrain.registry import analyzers

ORDER = ["relief", "min_width", "bed_fit", "spacing", "resolution"]


def run_all(ctx: AnalysisContext) -> dict[str, AnalyzerResult]:
    return {name: analyzers.get(name).analyze(ctx) for name in ORDER}


def format_analysis(results: dict[str, AnalyzerResult]) -> str:
    """Warnings first, each followed by its fix in plain words, then key numbers."""
    rank = {"error": 0, "warn": 1, "info": 2}
    items = sorted(
        (s for r in results.values() for s in r.suggestions), key=lambda s: rank[s.severity]
    )
    lines = []
    for s in items:
        lines.append(f"{s.severity.upper()}: {s.message}")
        if s.patch:
            lines.append(f"  Fix: {describe_patch(s.patch)}.")
    if not items:
        lines.append("No problems found.")
    m = results["relief"].metrics
    if m:
        lines.append(
            f"Relief: {m['max_relief_mm']:.1f} mm maximum above the base, "
            f"{m['relief_spread_mm']:.1f} mm spread (98th minus 2nd percentile), "
            f"total height {m['total_height_mm']:.1f} mm."
        )
    return "\n".join(lines)


__all__ = ["AnalysisContext", "AnalyzerResult", "Suggestion", "format_analysis", "run_all"]
