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
from types import SimpleNamespace
from typing import Any

import numpy as np
import shapely
from scipy import ndimage
from shapely.geometry import LineString, MultiLineString, Point

from tactile_terrain.analyzers.base import AnalysisContext
from tactile_terrain.analyzers.spacing import Spacing
from tactile_terrain.compose import PlacedLine
from tactile_terrain.config import DescribeSettings, PrinterProfile
from tactile_terrain.pipeline.stages import WATER_TYPES, Heightfield
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


def _wrap(m: DescribeInput, text: str, indent: str = "", bullet: bool = False) -> list[str]:
    """Wrap to the describe width without splitting a coordinate or a measurement.

    A bullet is a Markdown list item: "- " on the first line, continuation lines aligned under it.
    """
    glued = GLUED.sub(lambda hit: hit.group(0).replace(" ", GLUE), text)
    first = indent + "- " if bullet else indent
    wrapped = textwrap.wrap(
        glued,
        width=m.settings.wrap_chars,
        initial_indent=first,
        subsequent_indent=indent + ("  " if bullet else ""),
    )
    return [line.replace(GLUE, " ") for line in wrapped] or [""]


def _bullets(m: DescribeInput, texts: list[str], indent: str = "") -> list[str]:
    return [line for text in texts for line in _wrap(m, text, indent, bullet=True)]


def _sub(title: str) -> list[str]:
    """A third-level heading with blank lines around it."""
    return ["", f"### {title}", ""]


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
        f"- Model: {m.spec.name}",
        (
            f"- Footprint: {width:.1f} mm east-west by {depth:.1f} mm north-south, "
            f"{top:.1f} mm tall in total."
        ),
        (
            f"- Scale: 1 mm = {t.scale_m_per_mm:g} m horizontally. "
            f"Vertical exaggeration: {t.z_exaggeration:g} times."
        ),
        (
            f"- Mode: {m.spec.mode}. Tactile profile: {m.spec.style.tactile_profile}. "
            f"Printer: {m.spec.print.printer}."
        ),
    ]
    for label, path in m.paths.items():
        lines.append(f"- {label}: {path}")
    return lines


def orientation(m: DescribeInput) -> list[str]:
    return [
        "Orientation",
        "- North is the far edge, where y is largest. East is the right edge, where x is largest.",
        "- The origin, x = 0 mm and y = 0 mm, is the south-west corner nearest you.",
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
        return ["High and low points", "- Flat model: there is no terrain, only the base."]
    lines = ["High and low points", *_sub("Highest points, highest first")]
    for x, y, height in _summits(m):
        named = _near_points(m, x, y, {"peak"}, m.settings.peak_name_radius_mm)
        text = _point_text(m, x, y, height, named[0].name if named else None)
        lines += _wrap(m, text, bullet=True)
    z, g = m.terrain, m.hf.grid_mm
    j, i = np.unravel_index(np.argmin(z), z.shape)
    lines += _sub("Lowest point")
    lines += _wrap(m, _point_text(m, i * g, j * g, float(z[j, i]), None), bullet=True)
    return lines


def _orient(m: DescribeInput, line: PlacedLine, part: LineString) -> list[tuple[float, float]]:
    """Walk lifts from the lower terminal up and water downstream, else from the south end."""
    coords = list(part.coords)
    first, last = coords[0], coords[-1]
    if line.feature_type == LIFT_TYPE:
        reverse = _terrain_at(m, *first) > _terrain_at(m, *last)
    elif _flow_known(m, line, part):
        reverse = _elevation_at(m, *first) < _elevation_at(m, *last)  # water runs downhill
    else:
        reverse = (last[1], last[0]) < (first[1], first[0])
    return coords[::-1] if reverse else coords


def _flow_known(m: DescribeInput, line: PlacedLine, part: LineString) -> bool:
    """Water direction is read from the ground: only when the two ends differ clearly."""
    if line.feature_type not in WATER_TYPES:
        return False
    (x0, y0), (x1, y1) = part.coords[0], part.coords[-1]
    drop = abs(_elevation_at(m, x0, y0) - _elevation_at(m, x1, y1))
    return drop >= m.settings.level_change_m


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
    lead = "Walked downstream (with the flow): " if _flow_known(m, line, part) else ""
    return lead + ", then ".join([start, *parts, end]) + "."


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
    for group in _entities(m):
        first = group[0]
        if len(group) == 1:
            head = f"{_cap(_label(first))} ({first.feature_type}, style {first.style.name})"
        else:
            kinds = " and ".join(
                dict.fromkeys(f"{g.feature_type} style {g.style.name}" for g in group)
            )
            head = f"{_cap(_label(first))} ({kinds})"
        total = sum(_length(g) for g in group)
        lines += _sub(f"{head}, {total:.0f} mm long")
        lines += [*_wrap(m, _story(m, group)), "", "Turn by turn:", ""]
        pieces = sorted(
            ((g, part) for g in group for part in _parts(g)), key=lambda gp: -gp[1].length
        )
        for n, (line, part) in enumerate(pieces):
            prefix = ""
            if len(pieces) > 1:
                prefix = f"Piece {chr(ord('A') + n)}"
                if len(group) > 1:
                    prefix += f", {line.feature_type} style {line.style.name}"
                prefix += ": "
            walk = (
                _lift_text(m, line, part)
                if line.feature_type == LIFT_TYPE
                else _walk_text(m, line, part)
            )
            lines += _wrap(m, prefix + _cap(walk), bullet=True)
    return lines


def _entities(m: DescribeInput) -> list[list[PlacedLine]]:
    """Lines grouped by what they are: one named stream drawn in two styles is one entity."""
    groups: dict[object, list[PlacedLine]] = {}
    for n, line in enumerate(m.hf.lines):
        shared = line.name and line.feature_type in WATER_TYPES
        groups.setdefault(("water", line.name) if shared else n, []).append(line)
    return sorted(groups.values(), key=lambda g: -sum(_length(line) for line in g))


# --- plain-English prose ------------------------------------------------------------------

M_PER_KM = 1000  # unit conversion, not a tactile number
REGION_GRID = [
    ["south-west", "south", "south-east"],
    ["west", "middle", "east"],
    ["north-west", "north", "north-east"],
]  # rows run south to north
NUMBER_WORDS = [
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]  # fmt: skip
OPPOSITE = {name: COMPASS[(n + len(COMPASS) // 2) % len(COMPASS)] for n, name in enumerate(COMPASS)}


def _count(n: int) -> str:
    return NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else "many"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _region(m: DescribeInput, x: float, y: float) -> str:
    width, depth = m.extent
    rows, cols = len(REGION_GRID), len(REGION_GRID[0])
    row = min(max(int(y / depth * rows), 0), rows - 1)
    col = min(max(int(x / width * cols), 0), cols - 1)
    return REGION_GRID[row][col]


def _place(m: DescribeInput, x: float, y: float) -> str:
    region = _region(m, x, y)
    return "the middle of the map" if region == "middle" else f"the {region} part of the map"


def _round_elevation(m: DescribeInput, metres: float) -> float:
    step = m.settings.elevation_round_m
    return round(metres / step) * step


def _ground(m: DescribeInput, mm: float) -> str:
    metres = mm * m.hf.transform.scale_m_per_mm
    if metres >= M_PER_KM:
        return f"{metres / M_PER_KM:.1f} km"
    return f"{_round_elevation(m, metres):.0f} m"


def _kind_word(group: list[PlacedLine]) -> str:
    kinds = {g.feature_type for g in group}
    return "stream" if len(kinds) > 1 else group[0].feature_type


def _end_text(m: DescribeInput, group: list[PlacedLine], end: tuple[float, float]) -> str:
    x, y = end
    edge = _edge_of(m, x, y)
    if edge is not None:
        return f"leaves the map at the {edge[0]} edge"
    point = Point(x, y)
    names = {g.name for g in group}
    reach = m.settings.run_end_touch_mm  # "meets" needs the lines to actually touch
    near = [
        (line.geometry.distance(point), line.name)
        for line in m.hf.lines
        if line.name and line.name not in names and line.geometry.distance(point) <= reach
    ]
    if near:
        return f"meets {min(near)[1]}"
    return f"ends inside the map in {_place(m, x, y)}"


def _story(m: DescribeInput, group: list[PlacedLine]) -> str:
    """A short plain-English account of one named feature."""
    s = m.settings
    first = group[0]
    kind = _kind_word(group)
    merged = shapely.line_merge(shapely.union_all([g.geometry for g in group]))
    parts = sorted(getattr(merged, "geoms", [merged]), key=lambda p: -p.length)
    main = parts[0]
    total = sum(_length(g) for g in group)
    article = "an" if kind[:1] in "aeiou" else "a"
    if first.name:
        text = f"{_cap(first.name)} is {article} {kind} about {_ground(m, total)} long."
    else:
        text = f"There is an unnamed {kind} about {_ground(m, total)} long."
    coords = _orient(m, first, main)
    (x0, y0), (x1, y1) = coords[0], coords[-1]
    chord = math.hypot(x1 - x0, y1 - y0)
    e0, e1 = _elevation_at(m, x0, y0), _elevation_at(m, x1, y1)
    change = _round_elevation(m, abs(e1 - e0))
    if chord == 0:
        text += " It loops back to where it started."
    else:
        heading = COMPASS[_bearing_index(x1 - x0, y1 - y0)]
        ratio = main.length / chord
        go = "flows" if _flow_known(m, first, main) else "runs"  # water is told downstream
        if first.feature_type == LIFT_TYPE:
            text += f" It runs {heading}."
        elif ratio <= s.straight_ratio:
            text += f" It {go} nearly straight {heading}."
        else:
            across = "east and west" if abs(y1 - y0) >= abs(x1 - x0) else "north and south"
            how = "winds" if ratio >= s.meander_ratio else "wanders"
            text += f" It generally {go} {heading}, and {how} {across} along the way."
        text += " " + _elevation_text(
            m, first, group, (x0, y0), (x1, y1), e0, e1, change, _flow_known(m, first, main)
        )
    if len(parts) > 1:
        text += f" It also has {_count(len(parts) - 1)} shorter separate piece"
        text += "s." if len(parts) > 2 else "."
    return text


def _elevation_text(m, first, group, start, end, e0, e1, change, flow_known=False) -> str:
    s = m.settings
    heading = COMPASS[_bearing_index(end[0] - start[0], end[1] - start[1])]
    if first.feature_type == LIFT_TYPE:
        return (
            f"It climbs about {change:.0f} m from the bottom terminal in {_place(m, *start)} "
            f"to the top terminal in {_place(m, *end)}."
        )
    if flow_known:  # the path is already walked downstream, so its end is where the water goes
        return (
            f"It loses about {change:.0f} m of elevation along the way, and the water then "
            f"{_end_text(m, group, end)}."
        )
    if abs(e1 - e0) < s.level_change_m:
        text = (
            f"It stays at about the same elevation, within {s.level_change_m:.0f} m, "
            f"and {_end_text(m, group, end)}."
        )
        if first.feature_type in WATER_TYPES:
            text += " The ground is too level to tell which way the water flows."
        return text
    verb = "climbs" if e1 > e0 else "descends"
    return f"Going {heading} it {verb} about {change:.0f} m, and then {_end_text(m, group, end)}."


def _terrain_regions(m: DescribeInput) -> list[str]:
    """Plain-English account of high and low ground by part of the map."""
    rows, cols = len(REGION_GRID), len(REGION_GRID[0])
    z = m.terrain
    means = {}
    for r, row_block in enumerate(np.array_split(z, rows, axis=0)):
        for c, cell in enumerate(np.array_split(row_block, cols, axis=1)):
            means[REGION_GRID[r][c]] = float(m.hf.transform.z_to_elevation(cell.mean()))
    ordered = sorted(means, key=means.get)
    high, low = ordered[-rows:], ordered[:rows]
    lo, hi = (
        float(m.hf.transform.z_to_elevation(z.min())),
        float(m.hf.transform.z_to_elevation(z.max())),
    )
    j, i = np.unravel_index(np.argmin(z), z.shape)
    lo_at = _region(m, i * m.hf.grid_mm, j * m.hf.grid_mm)
    j, i = np.unravel_index(np.argmax(z), z.shape)
    hi_at = _region(m, i * m.hf.grid_mm, j * m.hf.grid_mm)
    lines = [
        (
            f"Ground elevation runs from about {_round_elevation(m, lo):.0f} m in the {lo_at} up to "
            f"about {_round_elevation(m, hi):.0f} m in the {hi_at}, a difference of about "
            f"{_round_elevation(m, hi - lo):.0f} m."
        ),
    ]
    if hi - lo >= m.settings.level_change_m:
        lines.append(f"The highest ground is in the {_join(high)}.")
        lines.append(f"The lowest ground is in the {_join(low)}.")
    else:
        lines = ["The ground is nearly level."]
    peaks: dict[str, list[str]] = {}
    for x, y, height in _summits(m):
        named = _near_points(m, x, y, {"peak"}, m.settings.peak_name_radius_mm)
        if named:
            elevation = _round_elevation(m, float(m.hf.transform.z_to_elevation(height)))
            peaks.setdefault(_region(m, x, y), []).append(f"{named[0].name} ({elevation:.0f} m)")
    if peaks:
        told = [f"{_join(names)} in the {region}" for region, names in peaks.items()]
        lines.append(f"Named peaks: {_join(told)}.")
    return lines


def overview(m: DescribeInput) -> list[str]:
    """Plain-English opening: size, ground, regions and the main features."""
    t = m.hf.transform
    width, depth = m.extent
    lines = [
        "Overview",
        (
            "This overview is plain English. The detailed sections after it give exact positions "
            "and each starts with a heading, so you can skip to the one you want."
        ),
        "",
        (
            f"This model covers about {_ground(m, width)} east-west by {_ground(m, depth)} "
            f"north-south. North is the far edge. Heights are exaggerated {t.z_exaggeration:g} times."
        ),
    ]
    if m.spec.mode != "flat":
        lines += ["", *_wrap(m, " ".join(_terrain_regions(m)))]
    entities = _entities(m)
    if entities:
        lines += ["", "The longest features:", ""]
        for group in entities[: m.settings.overview_features]:
            lines += _wrap(m, _story(m, group), bullet=True)
        by_kind: dict[str, list[list[PlacedLine]]] = {}
        for group in entities:
            by_kind.setdefault(_kind_word(group), []).append(group)
        counts = [f"{_count(len(v))} {k}{'s' if len(v) != 1 else ''}" for k, v in by_kind.items()]
        lines += ["", *_wrap(m, f"In all, the map has {_join(counts)}.")]
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
        return [*lines, "- No line features cross or meet."]
    for x, y, a, b, verb, top, other in sorted(found, key=lambda f: (f[1], f[0])):
        text = (
            f"{_cap(_label(a))} {verb} {_label(b)} at x = {x:.0f} mm, y = {y:.0f} mm. "
            f"{_cap(_label(top))} is on top ({top.style.height_mm:g} mm tall "
            f"against {other.style.height_mm:g} mm)."
        )
        lines += _wrap(m, text, bullet=True)
    return lines


def close_parallels(m: DescribeInput) -> list[str]:
    lines = ["Close parallels"]
    ctx = AnalysisContext(m.spec, m.profile, m.printer, m.hf, m.source_resolution_m)
    result = Spacing().analyze(ctx)
    if not result.suggestions:
        return [*lines, "- No two lines run too close together."]
    for s in result.suggestions:
        lines += _wrap(m, s.message, bullet=True)
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
    to_elevation = m.hf.transform.z_to_elevation
    cells = []
    for p in positions:
        height = float(samples[min(round(p / g), len(samples) - 1)])
        cells.append(
            f"{label} = {p:g} mm: {height:.1f} mm ({float(to_elevation(height)):.0f} m)".replace(
                " ", GLUE
            )
        )
    return _wrap(m, "; ".join(cells))


def _extra_section(m: DescribeInput, request: dict[str, Any]) -> list[str]:
    step = m.settings.extra_section_step_mm
    every = f"every {step:g} mm"
    if "y_mm" in request:
        head = f"East-west section at y = {request['y_mm']:g} mm, {every}"
        return [*_sub(head), *_section_values(m, "EW", request["y_mm"], step)]
    if "x_mm" in request:
        head = f"North-south section at x = {request['x_mm']:g} mm, {every}"
        return [*_sub(head), *_section_values(m, "NS", request["x_mm"], step)]
    if "through" in request:
        name = request["through"]
        x, y = _locate(m, name)
        direction = request.get("direction", "EW")
        word = "East-west" if direction == "EW" else "North-south"
        fixed = f"y = {y:.0f} mm" if direction == "EW" else f"x = {x:.0f} mm"
        head = f"{word} section through {name} at {fixed}, {every}"
        return [*_sub(head), *_section_values(m, direction, y if direction == "EW" else x, step)]
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
        lines += _sub(f"East-west section at y = {at:.0f} mm ({fraction:.0%} of the way north)")
        lines += _section_values(m, "EW", at, s.section_step_mm)
    for fraction in s.section_fractions_x:
        at = fraction * width
        lines += _sub(f"North-south section at x = {at:.0f} mm ({fraction:.0%} of the way east)")
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
            bullet=True,
        )
    if not seen:
        lines.append("- No line features are used.")
    return lines


def distortion(m: DescribeInput) -> list[str]:
    t = m.hf.transform
    real_per_mm = t.scale_m_per_mm / t.z_exaggeration
    return [
        "Distortion",
        f"- No horizontal distortion: 1 mm = {t.scale_m_per_mm:g} m in every direction.",
        (
            f"- Vertical exaggeration is {t.z_exaggeration:g} times everywhere, so 1 mm of height "
            f"stands for {real_per_mm:.1f} m of real elevation."
        ),
    ]


def attribution(m: DescribeInput) -> list[str]:
    from tactile_terrain.attribution import sources_used

    names = ", ".join(info.name for info in sources_used(m.spec))
    text = f"Data from {names}. Full credits are in ATTRIBUTION.txt."
    return ["Attribution", *_wrap(m, text, bullet=True)]


def _markdown(title: str, blocks: list[list[str]]) -> str:
    """Join sections under a title: each block's first line is its second-level heading."""
    parts = [f"# {title}"]
    for heading, *body in blocks:
        parts += ["", f"## {heading}", "", *body]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).rstrip("\n") + "\n"


def _requested_sections(m: DescribeInput, extra: list[dict[str, Any]]) -> list[str]:
    lines = ["Requested cross-sections", "Terrain height without raised lines."]
    for request in extra:
        lines += _extra_section(m, request)
    return lines


def describe(
    m: DescribeInput,
    extra_sections: list[dict[str, Any]] | None = None,
    brief_warnings: str | None = None,
) -> str:
    """The full description. With `brief_warnings` (the analysis text) only the short form."""
    if brief_warnings is not None:
        warnings = ["Warnings and checks", *_bullets(m, brief_warnings.splitlines())]
        more = [
            "More detail",
            (
                "- Call describe_model without brief for exact positions, every line's course, "
                "crossings and cross-sections."
            ),
        ]
        blocks = [overview(m), warnings, legend(m), distortion(m)]
        if extra_sections:
            blocks.append(_requested_sections(m, extra_sections))
        blocks.append(more)
        return _markdown(f"Tactile model description (brief): {m.spec.name}", blocks)
    blocks = [
        overview(m),
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
    return _markdown(f"Tactile model description: {m.spec.name}", blocks)


# --- sampler plates -----------------------------------------------------------------------

ROW_TITLES = {
    "profiles": "profile pairs: do the two lines of each pair feel the same or different",
    "widths": "widths: rounded lines from narrow to wide",
    "heights": "heights: rounded lines from low to tall",
    "spacing": "spacing: pairs of lines with the gap between them getting smaller",
}


def _shape(name: str) -> str:
    return name.replace("_", "-")


def _line_words(line) -> str:
    return f"{_shape(line.shape)}, {line.width_mm:g} mm wide, {line.height_mm:g} mm tall"


def _cell_text(cell) -> str:
    where = f"Row {cell.row}, sample {cell.number}: "
    first = cell.lines[0]
    if cell.kind == "profiles":
        second = cell.lines[1]
        lower = (
            "the same again, so this pair is identical"
            if second.shape == first.shape
            else _line_words(second)
        )
        return f"{where}upper line {_line_words(first)}; lower line {lower}."
    if cell.kind == "spacing":
        return (
            f"{where}two lines, each {_shape(first.shape)}, {first.width_mm:g} mm wide and "
            f"{first.height_mm:g} mm tall, with a {cell.gap_mm:g} mm gap between their edges."
        )
    return f"{where}{_line_words(first)}."


def describe_sampler(plate, spec, paths: dict[str, str], settings: DescribeSettings) -> str:
    """Row-by-row readout of a sampler plate. It replaces the terrain sections."""
    m = SimpleNamespace(settings=settings)
    shortened = ""
    if plate.sample_length_mm < plate.requested_length_mm:
        shortened = (
            f" Samples were shortened from {plate.requested_length_mm:g} mm to fit the plate."
        )
    summary = [
        "Summary",
        f"- Sampler plate {spec.name}, made with the {spec.style.tactile_profile} tactile profile.",
        (
            f"- Plate: {plate.width_mm:.1f} mm east-west by {plate.height_mm:.1f} mm north-south, "
            f"{plate.base_mm:g} mm base. Printer: {spec.print.printer}."
        ),
        *_wrap(
            m,
            f"Every sample is a straight line {plate.sample_length_mm:g} mm long running "
            f"east-west.{shortened} Shuffle seed {plate.seed}.",
            bullet=True,
        ),
    ]
    summary += [f"- {label}: {path}" for label, path in paths.items()]
    notes = [
        "North is the far edge. The origin, x = 0 mm and y = 0 mm, is the south-west corner.",
        (
            "One notch in the middle of the north edge marks north. Notches on the left edge "
            "give the row: one notch for row one, two for row two, and so on from north to south."
        ),
        (
            "Each sample has a raised numeral below it. Count the notches to find the row, "
            "then read the numeral to find the sample. Braille is not needed."
        ),
        (
            "Feel the plate first and note which pairs feel the same and which feel different, "
            "and where lines merge. This list reveals the answers, including which pairs are "
            "identical controls."
        ),
    ]
    notches = ["Orientation", *_bullets(m, notes)]
    body = ["Rows"]
    for row in plate.rows:
        y0 = row.top_mm - row.height_mm
        body += _sub(
            f"Row {row.number}, {ROW_TITLES[row.kind]}. Between y = {y0:.0f} mm and "
            f"y = {row.top_mm:.0f} mm"
        )
        for cell in row.cells:
            text = f"{_cell_text(cell)} Numeral {cell.number} at x = {cell.centre_x_mm:.0f} mm."
            body += _wrap(m, text, bullet=True)
    credit = ["Attribution", "- No map data is used in a sampler plate."]
    return _markdown(
        f"Tactile sampler plate description: {spec.name}", [summary, notches, body, credit]
    )
