"""Digits 0-9 as polylines in a unit box (seven-segment style), with no font dependency.

Each digit is a list of polylines of (u, v) points with u across (0 to 1) and v up (0 to 1).
Numerals are drawn as raised strokes, so a blind user can feel the number of a sample
without reading Braille (invariant 3).
"""

from __future__ import annotations

ASPECT = 0.6  # digit width divided by digit height

# Seven segments on the unit box: top a, upper right b, lower right c, bottom d, lower left e,
# upper left f, middle g.
SEGMENTS = {
    "a": [(0.0, 1.0), (1.0, 1.0)],
    "b": [(1.0, 1.0), (1.0, 0.5)],
    "c": [(1.0, 0.5), (1.0, 0.0)],
    "d": [(0.0, 0.0), (1.0, 0.0)],
    "e": [(0.0, 0.0), (0.0, 0.5)],
    "f": [(0.0, 0.5), (0.0, 1.0)],
    "g": [(0.0, 0.5), (1.0, 0.5)],
}
LIT = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def digit_polylines(digit: str) -> list[list[tuple[float, float]]]:
    return [SEGMENTS[segment] for segment in LIT[digit]]


def number_width(text: str, height: float, gap: float) -> float:
    """Total width of a numeral whose digits are `height` tall, `gap` apart."""
    digit = ASPECT * height
    return len(text) * digit + (len(text) - 1) * gap


def number_polylines(
    text: str, height: float, gap: float, left: float, bottom: float
) -> list[list[tuple[float, float]]]:
    """The strokes of `text` in print mm, its lower-left corner at (left, bottom)."""
    digit = ASPECT * height
    lines = []
    for n, char in enumerate(text):
        x0 = left + n * (digit + gap)
        for polyline in digit_polylines(char):
            lines.append([(x0 + u * digit, bottom + v * height) for u, v in polyline])
    return lines
