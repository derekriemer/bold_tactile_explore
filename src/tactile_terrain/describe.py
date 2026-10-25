"""describe_model: the full text description of a model (invariant 4: every output is text).

Plain text, headings and short lines, units on every number, positions in print mm measured
from the south-west corner. No numeric thresholds live here; they come from the describe
settings in the user config (invariant 1).
"""

from __future__ import annotations

import itertools
import math
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString, Point

from tactile_terrain.analyzers.base import AnalysisContext
from tactile_terrain.analyzers.spacing import Spacing
from tactile_terrain.compose import PlacedLine
from tactile_terrain.config import DescribeSettings, PrinterProfile
from tactile_terrain.pipeline.stages import Heightfield
from tactile_terrain.providers.names import name_matches
from tactile_terrain.spec import Spec
from tactile_terrain.tactile.profile import TactileProfile

COMPASS = [
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
]
PROFILE_WORDS = {
    "rounded": "rounded ridge",
    "flat_top": "flat-topped ridge",
    "pointed": "pointed ridge",
}
LIFT_TYPE = "lift"


@dataclass
class PrintPoint:
    """A named peak, pass or saddle placed in print coordinates."""

    name: str
    kind: str
    x: float
    y: float
    elevation_m: float | None = None


@dataclass
class DescribeInput:
    spec: Spec
    profile: TactileProfile
    printer: PrinterProfile
    hf: Heightfield
    settings: DescribeSettings
    points: list[PrintPoint] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)  # label -> path, for the summary
    source_resolution_m: float | None = None

    @property
    def terrain(self) -> np.ndarray:
        return self.hf.terrain_z if self.hf.terrain_z is not None else self.hf.z

    @property
    def extent(self) -> tuple[float, float]:
        ny, nx = self.hf.z.shape
        return (nx - 1) * self.hf.grid_mm, (ny - 1) * self.hf.grid_mm


# --- helpers ------------------------------------------------------------------------------


GLUE = "\x01"  # stands in for a space that wrapping must not break
GLUED = re.compile(r"\b[xy] = -?[\d.]+ mm|-?[\d.]+ (?:mm|m|km|times)\b")


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _wrap(m: DescribeInput, text: str, indent: str = "") -> list[str]:
    """Wrap to the describe width without splitting a coordinate or a measurement."""
    glued = GLUED.sub(lambda hit: hit.group(0).replace(" ", GLUE), text)
    wrapped = textwrap.wrap(
        glued, width=m.settings.wrap_chars, initial_indent=indent, subsequent_indent=indent + "  "
    )
    return [line.replace(GLUE, " ") for line in wrapped] or [""]


def _label(line: PlacedLine) -> str:
    return line.name or f"unnamed {line.feature_type}"


def _parts(line: PlacedLine) -> list[LineString]:
    geom = line.geometry
    return list(geom.geoms) if isinstance(geom, MultiLineString) else [geom]


def _length(line: PlacedLine) -> float:
    return float(line.geometry.length)


def _terrain_at(m: DescribeInput, x: float, y: float) -> float:
    g = m.hf.grid_mm
    ny, nx = m.terrain.shape
    i = min(max(round(x / g), 0), nx - 1)
    j = min(max(round(y / g), 0), ny - 1)
    return float(m.terrain[j, i])


def _elevation_at(m: DescribeInput, x: float, y: float) -> float:
    return float(m.hf.transform.z_to_elevation(_terrain_at(m, x, y)))


def _bearing_index(dx: float, dy: float) -> int:
    angle = math.atan2(dx, dy)  # clockwise from north
    return round(angle / (math.tau / len(COMPASS))) % len(COMPASS)


def _edge_of(m: DescribeInput, x: float, y: float) -> tuple[str, float] | None:
    """The border a point lies on, with the coordinate along it, or None."""
    width, depth = m.extent
    tol = m.settings.edge_tolerance_mm
    if abs(y) <= tol:
        return "south", x
    if abs(y - depth) <= tol:
        return "north", x
    if abs(x) <= tol:
        return "west", y
    if abs(x - width) <= tol:
        return "east", y
    return None


def _near_points(m: DescribeInput, x: float, y: float, kinds: set[str], radius: float):
    near = [p for p in m.points if p.kind in kinds and math.hypot(p.x - x, p.y - y) <= radius]
    return sorted(near, key=lambda p: math.hypot(p.x - x, p.y - y))


# --- sections -----------------------------------------------------------------------------


def summary(m: DescribeInput) -> list[str]:
    width, depth = m.extent
    t = m.hf.transform
    top = float(m.hf.z.max())
    lines = [
        "Summary",
        f"Model: {m.spec.name}",
        (
            f"Footprint: {width:.1f} mm east-west by {depth:.1f} mm north-south, "
            f"{top:.1f} mm tall in total."
        ),
        (
            f"Scale: 1 mm = {t.scale_m_per_mm:g} m horizontally. "
            f"Vertical exaggeration: {t.z_exaggeration:g} times."
        ),
        (
            f"Mode: {m.spec.mode}. Tactile profile: {m.spec.style.tactile_profile}. "
            f"Printer: {m.spec.print.printer}."
        ),
    ]
    for label, path in m.paths.items():
        lines.append(f"{label}: {path}")
    return lines


def orientation(m: DescribeInput) -> list[str]:
    return [
        "Orientation",
        "North is the far edge, where y is largest. East is the right edge, where x is largest.",
        "The origin, x = 0 mm and y = 0 mm, is the south-west corner nearest you.",
    ]


def _summits(m: DescribeInput) -> list[tuple[float, float, float]]:
    """Local maxima as (x, y, z), highest first, each the highest within summit_radius_mm."""
    s = m.settings
    z, g = m.terrain, m.hf.grid_mm
    factor = max(1, round(s.summit_grid_mm / g))
    ny, nx = z.shape
    ty, tx = ny // factor, nx // factor
    tiles = z[: ty * factor, : tx * factor].reshape(ty, factor, tx, factor)
    coarse = tiles.max(axis=(1, tiles.ndim - 1))
    reach = max(1, round(s.summit_radius_mm / (g * factor)))
    yy, xx = np.ogrid[-reach : reach + 1, -reach : reach + 1]
    disk = (xx**2 + yy**2) <= reach**2
    peaks = coarse == ndimage.maximum_filter(coarse, footprint=disk, mode="constant", cval=-np.inf)
    found = []
    for cj, ci in zip(*np.nonzero(peaks), strict=True):
        window = z[cj * factor : (cj + 1) * factor, ci * factor : (ci + 1) * factor]
        wj, wi = np.unravel_index(np.argmax(window), window.shape)
        j, i = cj * factor + wj, ci * factor + wi
        found.append((float(z[j, i]), j, i))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    chosen: list[tuple[float, float, float]] = []
    for height, j, i in found:
        x, y = i * g, j * g
        if all(math.hypot(x - cx, y - cy) > s.summit_radius_mm for cx, cy, _ in chosen):
            chosen.append((x, y, height))
        if len(chosen) == s.summit_count:
            break
    return chosen


def _point_text(m: DescribeInput, x: float, y: float, height: float, name: str | None) -> str:
    elevation = float(m.hf.transform.z_to_elevation(height))
    label = f" ({name})" if name else ""
    return (
        f"x = {x:.0f} mm, y = {y:.0f} mm: {height:.1f} mm high, elevation {elevation:.0f} m{label}"
    )


def high_low_points(m: DescribeInput) -> list[str]:
    if m.spec.mode == "flat":
        return ["High and low points", "Flat model: there is no terrain, only the base."]
    lines = ["High and low points", "Highest points, highest first:"]
    for x, y, height in _summits(m):
        named = _near_points(m, x, y, {"peak"}, m.settings.peak_name_radius_mm)
        lines += _wrap(m, _point_text(m, x, y, height, named[0].name if named else None), "  ")
    z, g = m.terrain, m.hf.grid_mm
    j, i = np.unravel_index(np.argmin(z), z.shape)
    lines.append("Lowest point:")
    lines += _wrap(m, _point_text(m, i * g, j * g, float(z[j, i]), None), "  ")
    return lines


def _orient(m: DescribeInput, line: PlacedLine, part: LineString) -> list[tuple[float, float]]:
    """Walk lifts from the lower terminal up, everything else from the south end."""
    coords = list(part.coords)
    first, last = coords[0], coords[-1]
    if line.feature_type == LIFT_TYPE:
        reverse = _terrain_at(m, *first) > _terrain_at(m, *last)
    else:
        reverse = (last[1], last[0]) < (first[1], first[0])
    return coords[::-1] if reverse else coords


def _runs(m: DescribeInput, coords: list[tuple[float, float]]) -> list[list[Any]]:
    """Runs of [direction index, length, end x, end y], short wiggles absorbed."""
    runs: list[list[Any]] = []
    for (x0, y0), (x1, y1) in itertools.pairwise(coords):
        d = _bearing_index(x1 - x0, y1 - y0)
        length = math.hypot(x1 - x0, y1 - y0)
        if runs and runs[-1][0] == d:
            runs[-1][1] += length
            runs[-1][2:] = [x1, y1]
        else:
            runs.append([d, length, x1, y1])
    min_run = m.settings.describe_min_run_mm
    while len(runs) > 1:
        k = min(range(len(runs)), key=lambda n: runs[n][1])
        if runs[k][1] >= min_run:
            break
        neighbours = [n for n in (k - 1, k + 1) if 0 <= n < len(runs)]
        host = max(neighbours, key=lambda n: runs[n][1])
        runs[host][1] += runs[k][1]
        if host < k:  # absorbed into the previous run, which now ends where this one did
            runs[host][2:] = runs[k][2:]
        del runs[k]
        merged: list[list[Any]] = []
        for run in runs:
            if merged and merged[-1][0] == run[0]:
                merged[-1][1] += run[1]
                merged[-1][2:] = run[2:]
            else:
                merged.append(run)
        runs = merged
    return runs


def _walk_text(m: DescribeInput, line: PlacedLine, part: LineString) -> str:
    coords = _orient(m, line, part)
    (x0, y0), (x1, y1) = coords[0], coords[-1]
    entry = _edge_of(m, x0, y0)
    if entry is None:
        start = f"starts at x = {x0:.0f} mm, y = {y0:.0f} mm"
    else:
        edge, along = entry
        axis = "x" if edge in ("south", "north") else "y"
        start = f"enters the {edge} edge at {axis} = {along:.0f} mm"
    reach = m.settings.run_end_name_radius_mm
    parts = []
    for n, (d, length, ex, ey) in enumerate(_runs(m, coords)):
        text = f"{'runs ' if n == 0 else ''}{COMPASS[d]} for {length:.0f} mm"
        near = _near_points(m, ex, ey, {"peak", "pass", "saddle"}, reach)
        if near:
            text += f", passing near {near[0].name}"
        parts.append(text)
    leave = _edge_of(m, x1, y1)
    if leave is None:
        end = f"ends at x = {x1:.0f} mm, y = {y1:.0f} mm"
    else:
        edge, along = leave
        axis = "x" if edge in ("south", "north") else "y"
        end = f"exits the {edge} edge at {axis} = {along:.0f} mm"
    return ", then ".join([start, *parts, end]) + "."


def _lift_text(m: DescribeInput, line: PlacedLine, part: LineString) -> str:
    coords = _orient(m, line, part)
    (x0, y0), (x1, y1) = coords[0], coords[-1]
    scale = m.hf.transform.scale_m_per_mm
    direction = COMPASS[_bearing_index(x1 - x0, y1 - y0)]
    return (
        f"Bottom terminal at x = {x0:.0f} mm, y = {y0:.0f} mm, "
        f"elevation {_elevation_at(m, x0, y0):.0f} m. "
        f"Top terminal at x = {x1:.0f} mm, y = {y1:.0f} mm, "
        f"elevation {_elevation_at(m, x1, y1):.0f} m. "
        f"Length {part.length:.0f} mm ({part.length * scale:.0f} m on the ground), "
        f"heading {direction}."
    )


def line_features(m: DescribeInput) -> list[str]:
    lines = ["Line features"]
    if not m.hf.lines:
        return [*lines, "There are no line features."]
    for line in sorted(m.hf.lines, key=_length, reverse=True):
        head = f"{_cap(_label(line))} ({line.feature_type}, style {line.style.name}), "
        head += f"{_length(line):.0f} mm long."
        lines += ["", *_wrap(m, head)]
        parts = sorted(_parts(line), key=lambda p: -p.length)
        for n, part in enumerate(parts):
            prefix = "" if len(parts) == 1 else f"Piece {chr(ord('A') + n)}: "
            walk = (
                _lift_text(m, line, part)
                if line.feature_type == LIFT_TYPE
                else _walk_text(m, line, part)
            )
            lines += _wrap(m, prefix + _cap(walk), "  ")
    return lines


def _rank(m: DescribeInput, line: PlacedLine) -> tuple[float, int]:
    order = [f.type for f in m.spec.features]
    return (line.style.height_mm, -order.index(line.feature_type))


def crossings(m: DescribeInput) -> list[str]:
    lines = ["Crossings and junctions"]
    found = []
    for a_index, a in enumerate(m.hf.lines):
        for b in m.hf.lines[a_index + 1 :]:
            if a.name == b.name and (a.name or a.feature_type == b.feature_type):
                continue
            if not a.geometry.intersects(b.geometry):
                continue
            hit = a.geometry.intersection(b.geometry)
            for point in getattr(hit, "geoms", [hit]):
                if not isinstance(point, Point):
                    continue  # lines running together are reported as close parallels
                verb = "crosses" if a.geometry.crosses(b.geometry) else "meets"
                top, other = (a, b) if _rank(m, a) >= _rank(m, b) else (b, a)
                found.append((point.x, point.y, a, b, verb, top, other))
    if not found:
        return [*lines, "No line features cross or meet."]
    for x, y, a, b, verb, top, other in sorted(found, key=lambda f: (f[1], f[0])):
        text = (
            f"{_cap(_label(a))} {verb} {_label(b)} at x = {x:.0f} mm, y = {y:.0f} mm. "
            f"{_cap(_label(top))} is on top ({top.style.height_mm:g} mm tall "
            f"against {other.style.height_mm:g} mm)."
        )
        lines += _wrap(m, text, "  ")
    return lines


def close_parallels(m: DescribeInput) -> list[str]:
    lines = ["Close parallels"]
    ctx = AnalysisContext(m.spec, m.profile, m.printer, m.hf, m.source_resolution_m)
    result = Spacing().analyze(ctx)
    if not result.suggestions:
        return [*lines, "No two lines run too close together."]
    for s in result.suggestions:
        lines += _wrap(m, s.message, "  ")
    return lines


def _section_values(m: DescribeInput, axis: str, at_mm: float, step: float) -> list[str]:
    g = m.hf.grid_mm
    z = m.terrain
    width, depth = m.extent
    if axis == "EW":
        j = min(max(round(at_mm / g), 0), z.shape[0] - 1)
        samples, span, label = z[j, :], width, "x"
    else:
        i = min(max(round(at_mm / g), 0), z.shape[1] - 1)
        samples, span, label = z[:, i], depth, "y"
    return _format_samples(m, samples, span, step, label)


def _format_samples(m, samples, span, step, label) -> list[str]:
    g = m.hf.grid_mm
    positions = list(np.arange(0, span + step / 2, step))
    cells = [
        f"{label} = {p:g} mm: {samples[min(round(p / g), len(samples) - 1)]:.1f} mm".replace(
            " ", GLUE
        )
        for p in positions
    ]
    return _wrap(m, "; ".join(cells), "  ")


def _extra_section(m: DescribeInput, request: dict[str, Any]) -> list[str]:
    step = m.settings.extra_section_step_mm
    every = f"every {step:g} mm"
    if "y_mm" in request:
        head = f"East-west section at y = {request['y_mm']:g} mm, {every}:"
        return [head, *_section_values(m, "EW", request["y_mm"], step)]
    if "x_mm" in request:
        head = f"North-south section at x = {request['x_mm']:g} mm, {every}:"
        return [head, *_section_values(m, "NS", request["x_mm"], step)]
    if "through" in request:
        name = request["through"]
        x, y = _locate(m, name)
        direction = request.get("direction", "EW")
        word = "East-west" if direction == "EW" else "North-south"
        fixed = f"y = {y:.0f} mm" if direction == "EW" else f"x = {x:.0f} mm"
        head = f"{word} section through {name} at {fixed}, {every}:"
        return [head, *_section_values(m, direction, y if direction == "EW" else x, step)]
    raise ValueError("A section needs y_mm, x_mm or through.")


def _locate(m: DescribeInput, name: str) -> tuple[float, float]:
    for line in m.hf.lines:
        if name_matches(line.name, [name]):
            mid = line.geometry.interpolate(line.geometry.length / 2)
            return mid.x, mid.y
    for p in m.points:
        if name_matches(p.name, [name]):
            return p.x, p.y
    known = sorted({ln.name for ln in m.hf.lines if ln.name} | {p.name for p in m.points})
    raise ValueError(f"No feature or point named {name}. Known names: {', '.join(known)}")


def cross_sections(m: DescribeInput, extra: list[dict[str, Any]] | None = None) -> list[str]:
    s = m.settings
    width, depth = m.extent
    lines = [
        "Cross-sections",
        f"Terrain height without raised lines, every {s.section_step_mm:g} mm.",
    ]
    for fraction in s.section_fractions_y:
        at = fraction * depth
        lines.append(f"East-west section at y = {at:.0f} mm ({fraction:.0%} of the way north):")
        lines += _section_values(m, "EW", at, s.section_step_mm)
    for fraction in s.section_fractions_x:
        at = fraction * width
        lines.append(f"North-south section at x = {at:.0f} mm ({fraction:.0%} of the way east):")
        lines += _section_values(m, "NS", at, s.section_step_mm)
    for request in extra or []:
        lines += _extra_section(m, request)
    return lines


def legend(m: DescribeInput) -> list[str]:
    lines = ["Tactile legend"]
    seen = []
    for f in m.spec.features:
        key = (f.type, f.style)
        if key in seen:
            continue
        seen.append(key)
        entry = m.profile.lines[f.style]
        lines += _wrap(
            m,
            f"{_cap(f.type)}: {PROFILE_WORDS[entry.profile]}, {entry.width_mm:g} mm wide "
            f"and {entry.height_mm:g} mm tall (style {f.style}, from {f.provider}).",
            "  ",
        )
    if not seen:
        lines.append("No line features are used.")
    return lines


def distortion(m: DescribeInput) -> list[str]:
    t = m.hf.transform
    real_per_mm = t.scale_m_per_mm / t.z_exaggeration
    return [
        "Distortion",
        f"No horizontal distortion: 1 mm = {t.scale_m_per_mm:g} m in every direction.",
        (
            f"Vertical exaggeration is {t.z_exaggeration:g} times everywhere, so 1 mm of height "
            f"stands for {real_per_mm:.1f} m of real elevation."
        ),
    ]


def attribution(m: DescribeInput) -> list[str]:
    from tactile_terrain.attribution import sources_used

    names = ", ".join(info.name for info in sources_used(m.spec))
    return ["Attribution", *_wrap(m, f"Data from {names}. Full credits are in ATTRIBUTION.txt.")]


def describe(m: DescribeInput, extra_sections: list[dict[str, Any]] | None = None) -> str:
    blocks = [
        summary(m),
        orientation(m),
        high_low_points(m),
        line_features(m),
        crossings(m),
        close_parallels(m),
        cross_sections(m, extra_sections),
        legend(m),
        distortion(m),
        attribution(m),
    ]
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"
