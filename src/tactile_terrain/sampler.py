"""Sampler plate: a single-round calibration plate (invariants 1, 2 and 3).

The plate tests telling samples apart, not just feeling them: side-by-side pairs including
identical control pairs, a row of widths, a row of heights, and pairs of lines at decreasing
spacing. Every number comes from the tactile profile. Every cell has a raised numeral, and
each row is marked by counting notches on the left edge, so nothing depends on reading Braille.

Layout: sample lines run east-west. Rows are stacked from north to south with smooth gutters.
Each cell is a sample (or pair) with its numeral below it. Notches are slots in the plate edge:
a count of them on the left edge gives the row, and one on the north edge marks north.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiLineString

from tactile_terrain import glyphs
from tactile_terrain.compose import PlacedLine, raise_lines
from tactile_terrain.config import PrinterProfile
from tactile_terrain.spec import Spec
from tactile_terrain.styles import LineStyle
from tactile_terrain.tactile.profile import TactileProfile, apply_overrides, load_profile

ROW_KINDS = ["profiles", "widths", "heights", "spacing"]


@dataclass
class SampleLine:
    shape: str  # rounded | flat_top | pointed
    width_mm: float
    height_mm: float
    y_mm: float  # centre line
    x0_mm: float
    x1_mm: float


@dataclass
class Cell:
    row: int  # 1-based, equals the notch count on the left edge
    number: int  # 1-based position in the row, left to right, equals the numeral
    kind: str  # profiles | widths | heights | spacing
    control: bool  # identical pair
    gap_mm: float  # edge-to-edge gap between the lines of a pair
    lines: list[SampleLine]
    centre_x_mm: float
    label_strokes: list[list[tuple[float, float]]]
    label_box: tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class Row:
    number: int
    kind: str
    top_mm: float
    height_mm: float
    cells: list[Cell]
    notches: list[tuple[float, float, float, float]]


@dataclass
class Plate:
    width_mm: float
    height_mm: float
    base_mm: float
    grid_mm: float
    sample_length_mm: float
    requested_length_mm: float
    seed: int
    focus: str | None
    rows: list[Row]
    north_notch: tuple[float, float, float, float]
    z: np.ndarray
    profile: TactileProfile
    notch_floor_mm: float = 0
    cells: list[Cell] = field(default_factory=list)


@dataclass
class _CellSpec:
    kind: str
    control: bool
    gap_mm: float
    lines: list[tuple[str, float, float]]  # shape, width, height


def _reference(profile: TactileProfile, shape: str):
    """The profile's own line style for a shape, or its first style if none uses it."""
    for entry in profile.lines.values():
        if entry.profile == shape:
            return entry
    return next(iter(profile.lines.values()))


def _profile_pairs(profile: TactileProfile, rng: random.Random) -> list[_CellSpec]:
    shapes = list(profile.distinguishable_profiles)
    ref = _reference(profile, "flat_top")  # the road style: width and height for every pair
    pairs = [(a, b, False) for a, b in itertools.combinations(shapes, 2)]
    pairs += [(s, s, True) for s in shapes[:2]]  # identical controls, so guessing shows up
    rng.shuffle(pairs)
    specs = []
    for a, b, control in pairs:
        first, second = (a, b) if rng.choice([True, False]) else (b, a)
        lines = [(first, ref.width_mm, ref.height_mm), (second, ref.width_mm, ref.height_mm)]
        specs.append(_CellSpec("profiles", control, profile.sampler.pair_gap_mm, lines))
    return specs


def _row_specs(profile: TactileProfile, kind: str, rng: random.Random) -> list[_CellSpec]:
    s = profile.sampler
    ref = _reference(profile, "rounded")
    if kind == "profiles":
        return _profile_pairs(profile, rng)
    if kind == "widths":
        return [_CellSpec("widths", False, 0, [("rounded", w, ref.height_mm)]) for w in s.widths_mm]
    if kind == "heights":
        return [
            _CellSpec("heights", False, 0, [("rounded", ref.width_mm, h)]) for h in s.heights_mm
        ]
    both = [("rounded", ref.width_mm, ref.height_mm)] * 2
    return [_CellSpec("spacing", False, gap, both) for gap in s.spacings_mm]


def _group_height(spec: _CellSpec) -> float:
    return sum(w for _, w, _ in spec.lines) + spec.gap_mm * (len(spec.lines) - 1)


def _notch_span(profile: TactileProfile, count: int) -> float:
    nw = profile.notch_width_mm
    pitch = nw + nw / 2
    return nw + (count - 1) * pitch


def _layout(profile: TactileProfile, rows_specs: list[tuple[str, list[_CellSpec]]], length: float):
    """Place everything for one sample length. Returns (rows, width, height, north notch)."""
    s = profile.sampler
    nd, nw = profile.notch_depth_mm, profile.notch_width_mm
    label_h, stroke = profile.label_height_mm, profile.label_stroke_mm
    label_gap = digit_gap = 2 * stroke
    left, right, bottom = nd + s.margin_mm, s.margin_mm, s.margin_mm
    top_margin = nd + s.margin_mm

    heights = []
    for number, (_, specs) in enumerate(rows_specs, start=1):
        cell_h = max(_group_height(c) + label_gap + label_h for c in specs)
        heights.append(max(cell_h, _notch_span(profile, number)))
    columns = max(len(specs) for _, specs in rows_specs)
    width = left + columns * length + (columns - 1) * s.cell_gap_mm + right
    height = top_margin + sum(heights) + s.gutter_mm * (len(heights) - 1) + bottom

    rows: list[Row] = []
    row_top = height - top_margin
    for number, ((kind, specs), row_h) in enumerate(zip(rows_specs, heights, strict=True), start=1):
        cells = []
        for n, spec in enumerate(specs, start=1):
            x0 = left + (n - 1) * (length + s.cell_gap_mm)
            lines, cursor = [], row_top
            for shape, w, h in spec.lines:
                lines.append(SampleLine(shape, w, h, cursor - w / 2, x0, x0 + length))
                cursor -= w + spec.gap_mm
            text = str(n)
            inner_h = label_h - stroke
            label_w = glyphs.number_width(text, inner_h, digit_gap)
            label_bottom = row_top - _group_height(spec) - label_gap - label_h
            strokes = glyphs.number_polylines(
                text, inner_h, digit_gap, x0 + length / 2 - label_w / 2, label_bottom + stroke / 2
            )
            box = (
                x0 + length / 2 - label_w / 2 - stroke / 2,
                label_bottom,
                x0 + length / 2 + label_w / 2 + stroke / 2,
                label_bottom + label_h,
            )
            cells.append(
                Cell(
                    number, n, kind, spec.control, spec.gap_mm, lines, x0 + length / 2, strokes, box
                )
            )
        centre = row_top - row_h / 2
        pitch = nw + nw / 2
        notches = [
            (0, centre + (k - (number - 1) / 2) * pitch - nw / 2, nd,
             centre + (k - (number - 1) / 2) * pitch + nw / 2)
            for k in range(number)
        ]  # fmt: skip
        rows.append(Row(number, kind, row_top, row_h, cells, notches))
        row_top -= row_h + s.gutter_mm
    north = (width / 2 - nw / 2, height - nd, width / 2 + nw / 2, height)
    return rows, width, height, north


def _render(
    rows: list[Row], width: float, height: float, north, base: float, grid: float,
    profile: TactileProfile,
):  # fmt: skip
    nx, ny = math.ceil(width / grid) + 1, math.ceil(height / grid) + 1
    placed = []
    for row in rows:
        for cell in row.cells:
            for line in cell.lines:
                style = LineStyle(line.shape, line.shape, line.width_mm, line.height_mm)
                geometry = MultiLineString([[(line.x0_mm, line.y_mm), (line.x1_mm, line.y_mm)]])
                placed.append(PlacedLine(f"{line.shape} sample", "sample", style, geometry))
            label_style = LineStyle(
                "numeral", "flat_top", profile.label_stroke_mm, profile.label_relief_mm
            )
            placed.append(
                PlacedLine("numeral", "label", label_style, MultiLineString(cell.label_strokes))
            )
    z = raise_lines(np.full((ny, nx), base), grid, placed)

    floor = max(base - profile.notch_depth_mm, profile.label_relief_mm)
    rects = [n for row in rows for n in row.notches] + [north]
    for x0, y0, x1, y1 in rects:
        i0, i1 = math.ceil(x0 / grid), math.floor(x1 / grid)
        j0, j1 = math.ceil(y0 / grid), math.floor(y1 / grid)
        window = z[j0 : j1 + 1, i0 : i1 + 1]
        np.minimum(window, floor, out=window)
    return z, floor


def build_plate(spec: Spec, printer: PrinterProfile) -> Plate:
    """Lay out and render the plate a sampler spec describes. Deterministic for a given spec."""
    if spec.sampler is None:
        raise ValueError("This spec is not a sampler plate.")
    profile = apply_overrides(load_profile(spec.style.tactile_profile), spec.style.overrides)
    if profile.label_mode != "numerals":
        raise ValueError(
            "Braille labels are not available yet. Numerals are always present; set "
            "label_mode to numerals in the tactile profile."
        )
    info = spec.sampler
    kinds = ROW_KINDS if info.focus is None else [info.focus]
    unknown = set(kinds) - set(ROW_KINDS)
    if unknown:
        raise ValueError(f"Unknown focus {info.focus}. Valid names: {', '.join(ROW_KINDS)}")

    rng = random.Random(info.seed)
    rows_specs = [(kind, _row_specs(profile, kind, rng)) for kind in kinds]

    s = profile.sampler
    usable_x = printer.bed_mm[0] - 2 * printer.bed_margin_mm
    usable_y = printer.bed_mm[1] - 2 * printer.bed_margin_mm
    # The profile's preferred plate size first, then the whole usable bed.
    caps = [(min(s.plate_width_mm, usable_x), min(s.plate_height_mm, usable_y))]
    if caps[0] != (usable_x, usable_y):
        caps.append((usable_x, usable_y))
    base = float(spec.print.base_mm)

    layout = None
    for cap_w, cap_h in caps:
        length = s.sample_length_mm
        while length >= s.min_sample_length_mm:
            attempt = _layout(profile, rows_specs, length)
            if attempt[1] <= cap_w and attempt[2] <= cap_h:
                layout = attempt
                break
            length *= s.length_shrink
        if layout:
            break
    if layout is None:
        raise ValueError(
            f"The plate does not fit in {usable_x:g} mm by {usable_y:g} mm even with the "
            "shortest samples. Use focus to make a plate with one kind of row."
        )
    rows, width, height, north = layout

    z, floor = _render(rows, width, height, north, base, printer.grid_mm, profile)
    plate = Plate(
        width_mm=width,
        height_mm=height,
        base_mm=base,
        grid_mm=printer.grid_mm,
        sample_length_mm=length,
        requested_length_mm=s.sample_length_mm,
        seed=info.seed,
        focus=info.focus,
        rows=rows,
        north_notch=north,
        z=z,
        profile=profile,
        notch_floor_mm=floor,
    )
    plate.cells = [cell for row in rows for cell in row.cells]
    return plate
