"""Analyzer interface: metrics plus deterministic suggestions that carry their own patch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from tactile_terrain.config import PrinterProfile
    from tactile_terrain.pipeline.stages import Heightfield
    from tactile_terrain.spec import Spec
    from tactile_terrain.tactile.profile import TactileProfile

# Definitions fixed by the spec, not tactile thresholds (those all come from the profile).
PERCENTILE_LOW = 2  # relief spread is the 98th minus the 2nd percentile
PERCENTILE_HIGH = 98
Z_STEP = 0.5  # suggested z exaggeration is rounded to this step
SCALE_STEP = 5  # suggested scales are multiples of this many m per mm
NOZZLE_WIDTH_FACTOR = 3  # printable lines are at least this many nozzle widths wide
WORST_PLACES_REPORTED = 5
EPS = 1e-9  # numerical tolerance for rounding up
ROUND_DIGITS = 6  # suggested sizes are rounded to this many decimals

Severity = Literal["info", "warn", "error"]


@dataclass
class Suggestion:
    severity: Severity
    message: str
    patch: dict[str, Any] | None = None  # the exact update_model change that applies the fix


@dataclass
class AnalyzerResult:
    metrics: dict[str, Any] = field(default_factory=dict)
    suggestions: list[Suggestion] = field(default_factory=list)


@dataclass
class AnalysisContext:
    spec: Spec
    profile: TactileProfile  # with the spec's overrides applied
    printer: PrinterProfile
    hf: Heightfield
    source_resolution_m: float | None  # None in flat mode


class Analyzer(Protocol):
    name: str

    def analyze(self, ctx: AnalysisContext) -> AnalyzerResult: ...


def describe_patch(patch: dict[str, Any], prefix: str = "") -> str:
    """Plain-words version of a merge patch, for example "set print.z_exaggeration to 8.0"."""
    parts = []
    for key, value in patch.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            parts.append(describe_patch(value, path + "."))
        elif value is None:
            parts.append(f"remove {path}")
        else:
            parts.append(f"set {path} to {value}")
    return "; ".join(parts)


def round_to(value: float, step: float) -> float:
    return round(value / step) * step
