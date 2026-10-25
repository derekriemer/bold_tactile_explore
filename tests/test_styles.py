import numpy as np
import pytest

from tactile_terrain.styles import FLAT_TOP_SHOULDER_DEG, LineStyle, resolve_style
from tactile_terrain.tactile.profile import load_profile

D = np.linspace(0, 3, 3001)


def _styles():
    lines = load_profile("standard").lines
    return [LineStyle(name, e.profile, e.width_mm, e.height_mm) for name, e in lines.items()]


@pytest.mark.parametrize("style", _styles(), ids=lambda s: s.name)
def test_profile_shape(style):
    h = style.h(D)
    assert style.h(np.array([0.0]))[0] == pytest.approx(style.height_mm)
    assert style.h(np.array([style.width_mm / 2]))[0] == pytest.approx(0, abs=1e-9)
    assert (style.h(np.array([style.width_mm])) == 0).all()
    assert (np.diff(h) <= 1e-12).all()  # monotonic non-increasing


def test_flat_top_has_plateau_and_sixty_degree_shoulders():
    style = resolve_style("flat_top", load_profile("standard"))
    run = style.height_mm / np.tan(np.radians(FLAT_TOP_SHOULDER_DEG))
    plateau_edge = style.width_mm / 2 - run
    assert plateau_edge > 0
    inside = np.linspace(0, plateau_edge, 20)
    assert np.allclose(style.h(inside), style.height_mm)
    d0, d1 = plateau_edge + 0.1 * run, plateau_edge + 0.9 * run
    slope = (style.h(np.array([d0]))[0] - style.h(np.array([d1]))[0]) / (d1 - d0)
    assert np.degrees(np.arctan(slope)) == pytest.approx(FLAT_TOP_SHOULDER_DEG)


def test_pointed_flank_is_at_least_forty_five_degrees():
    style = resolve_style("pointed", load_profile("standard"))
    half = style.width_mm / 2
    slope = (style.h(np.array([0.0]))[0] - style.h(np.array([half]))[0]) / half
    assert np.degrees(np.arctan(slope)) >= 45 - 1e-9


def test_overrides_change_the_resolved_style():
    style = resolve_style(
        "rounded_major", load_profile("standard"), {"lines": {"rounded_major": {"width_mm": 2.4}}}
    )
    assert style.width_mm == 2.4 and style.height_mm == 1.0


def test_unknown_style_lists_valid_names():
    with pytest.raises(KeyError, match="rounded_major"):
        resolve_style("nope", load_profile("standard"))
