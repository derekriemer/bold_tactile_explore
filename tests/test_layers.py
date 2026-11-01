import pytest

from tactile_terrain.config import PrinterProfile, UserConfig
from tactile_terrain.layers import layer_count, snap_style, snap_up
from tactile_terrain.styles import LineStyle


@pytest.mark.parametrize(
    ("height", "layer", "expected"),
    [
        (0.4, 0.2, 0.4),  # already whole layers: unchanged, despite float noise
        (0.7, 0.2, 0.8),  # rounds up, never down
        (0.4, 0.3, 0.6),
        (0.6, 0.3, 0.6),
        (1.5, 0.2, 1.6),
        (0.4, 0.0, 0.4),  # unknown layer height: unchanged
    ],
)
def test_snap_up(height, layer, expected):
    assert snap_up(height, layer) == pytest.approx(expected)


def test_snap_never_lowers_a_height():
    for layer in (0.1, 0.15, 0.2, 0.25, 0.3):
        for height in (0.3, 0.4, 0.55, 0.7, 1.0, 1.2):
            assert snap_up(height, layer) >= height - 1e-9


def test_layer_count():
    assert layer_count(0.4, 0.2) == 2
    assert layer_count(0.4, 0.3) == 2  # snaps up to 0.6 mm first


def test_snap_style_keeps_other_fields():
    style = LineStyle("road", "rounded", 1.2, 0.7)
    snapped = snap_style(style, 0.2)
    assert (snapped.name, snapped.profile, snapped.width_mm) == ("road", "rounded", 1.2)
    assert snapped.height_mm == pytest.approx(0.8)


def test_pointed_flank_rule_survives_snapping():
    style = LineStyle("p", "pointed", 1.2, 0.6)
    assert snap_style(style, 0.25).height_mm >= style.width_mm / 2


def test_built_in_printers_and_old_configs():
    cfg = UserConfig()
    assert cfg.printer("louisville-library").layer_height_mm == pytest.approx(0.2)
    old = PrinterProfile(bed_mm=[100, 100, 100], nozzle_mm=0.4, grid_mm=0.2)
    assert old.layer_height_mm == 0  # a printer without the setting is not snapped
