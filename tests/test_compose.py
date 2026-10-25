import numpy as np
import pytest
from shapely.geometry import LineString

from tactile_terrain.compose import PlacedLine, compose
from tactile_terrain.styles import resolve_style
from tactile_terrain.tactile.profile import load_profile

G = 0.25
BASE = 3.0
PROFILE = load_profile("standard")
NX, NY = 161, 161  # 40 mm square


def _plane():
    return np.full((NY, NX), BASE)


def _line(style_name, y=20.0, x0=0.0, x1=40.0, name="line", type_="river"):
    style = resolve_style(style_name, PROFILE)
    return PlacedLine(name, type_, style, LineString([(x0, y), (x1, y)]))


@pytest.mark.parametrize("style_name", ["rounded_major", "rounded_minor", "flat_top", "pointed"])
def test_east_west_line_height_and_width(style_name):
    placed = _line(style_name)
    result = compose(_plane(), G, [placed], PROFILE)
    surface, style = result.surface, placed.style
    row = round(20.0 / G)
    column = surface[:, NX // 2]
    assert column[row] == pytest.approx(BASE + style.height_mm, abs=G)
    raised_width = (column > BASE).sum() * G
    assert raised_width == pytest.approx(style.width_mm, abs=G)
    assert surface.min() == BASE  # nothing dips below the terrain


def test_overlapping_features_take_the_taller_value():
    low = _line("rounded_minor", y=20.0)
    tall = _line("flat_top", y=20.0, name="road", type_="road")
    both = compose(_plane(), G, [low, tall], PROFILE).surface
    only_tall = compose(_plane(), G, [tall], PROFILE).surface
    assert np.array_equal(both, only_tall)  # the shorter, narrower profile is hidden
    assert both[round(20.0 / G), NX // 2] == pytest.approx(BASE + tall.style.height_mm)


def test_short_line_is_dropped_and_reported():
    short = PROFILE.min_feature_length_mm / 2
    placed = _line("rounded_major", x0=10.0, x1=10.0 + short, name="stub")
    result = compose(_plane(), G, [placed], PROFILE)
    assert result.lines == []
    assert [(d.name, round(d.length_mm, 6)) for d in result.dropped] == [("stub", short)]
    assert np.array_equal(result.surface, _plane())


def test_line_is_clipped_to_the_footprint():
    placed = _line("rounded_major", x0=-50.0, x1=90.0)
    result = compose(_plane(), G, [placed], PROFILE)
    assert result.surface.shape == (NY, NX)
    assert result.surface[round(20.0 / G), 0] > BASE


def test_surface_far_from_lines_is_exactly_base():
    result = compose(_plane(), G, [_line("pointed")], PROFILE)
    assert (result.surface[:20, :] == BASE).all()  # more than 4 mm from the line at y = 20 mm
