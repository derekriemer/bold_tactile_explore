"""Dashed lines (style.line_render = "dashed") on synthetic heightfields and one offline build."""

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE
from helpers import assert_printable

from tactile_terrain import api, dashes
from tactile_terrain.config import PrinterProfile
from tactile_terrain.geo import PrintTransform
from tactile_terrain.mesh import stl_size_mb
from tactile_terrain.pipeline import stages
from tactile_terrain.spec import DEFAULT_LINE_RENDER, Spec, load_spec, save_spec
from tactile_terrain.styles import flat_top
from tactile_terrain.tactile.profile import DashSettings, load_profile

RES = 0.2
DASH = DashSettings(height_mm=2.0, width_mm=2.0, length_mm=2.0, gap_mm=2.0)
LINE_Y = 20.0  # the synthetic line runs west-east at this y, in mm
LINE_HEIGHT = 1.5


def _ground(width_mm=60.0, height_mm=40.0):
    ny, nx = int(height_mm / RES) + 1, int(width_mm / RES) + 1
    yy, xx = np.mgrid[0:ny, 0:nx] * RES
    return 3.0 + 0.05 * xx + 0.02 * yy, xx, yy


def _with_line(ground, yy, x_from=5.0, x_to=55.0, xx=None):
    """A crisp flat-topped ridge, like a composed road, from x_from to x_to along LINE_Y."""
    ridge = flat_top(np.abs(yy - LINE_Y), 2.0, LINE_HEIGHT)
    if xx is not None:
        ridge = np.where((xx >= x_from) & (xx <= x_to), ridge, 0)
    return ground + ridge


@pytest.fixture(scope="module")
def line_map():
    ground, xx, yy = _ground()
    z = _with_line(ground, yy, xx=xx)
    return ground, z, dashes.apply(z, RES, DASH)


def test_a_crisp_line_is_found_and_a_smooth_ridge_is_not():
    ground, xx, yy = _ground()
    smooth = 2.0 * np.exp(-(((yy - 30.0) / 3.0) ** 2))  # a natural ridgeline, gentle flanks
    z = _with_line(ground + smooth, yy, xx=xx)
    band = dashes.detect_lines(np.asarray(z, np.float32).astype(float), RES)
    rows = np.flatnonzero(band.any(axis=1)) * RES
    assert band.any()
    assert np.all(np.abs(rows - LINE_Y) < 2.0), "only the crisp line is detected"


def test_ridge_is_filled_back_to_the_ground(line_map):
    ground, z, result = line_map
    under = np.abs(np.mgrid[0 : z.shape[0], 0 : z.shape[1]][0] * RES - LINE_Y) < 0.5
    assert np.abs(result.surface - ground)[under].max() < 0.05
    far = np.abs(np.mgrid[0 : z.shape[0], 0 : z.shape[1]][0] * RES - LINE_Y) > 3.0
    assert np.array_equal(result.surface[far], np.asarray(z, np.float32).astype(float)[far])


def test_blocks_follow_the_line_at_a_steady_spacing(line_map):
    ground, _, result = line_map
    blocks = sorted(result.blocks, key=lambda b: b.centre[0])
    assert len(blocks) >= 10
    xs = np.array([b.centre[0] for b in blocks])
    assert np.allclose(np.diff(xs), DASH.length_mm + DASH.gap_mm, atol=0.05)
    for b in blocks:
        assert abs(b.centre[1] - LINE_Y) < 0.1
        assert abs(abs(b.direction[0]) - 1) < 1e-3, "turned to follow a west-east line"
        ix, iy = round(b.centre[0] / RES), round(b.centre[1] / RES)
        assert b.top_mm == pytest.approx(ground[iy, ix] + DASH.height_mm, abs=0.02)
        assert b.bottom_mm < ground[iy, ix] - dashes.EMBED_MM + 0.05


def test_no_block_hangs_off_the_map():
    ground, _, yy = _ground()
    result = dashes.apply(_with_line(ground, yy), RES, DASH)  # the line runs edge to edge
    width = (ground.shape[1] - 1) * RES
    for b in result.blocks:
        assert DASH.length_mm / 2 <= b.centre[0] <= width - DASH.length_mm / 2


def test_dashed_mesh_is_one_watertight_solid(line_map):
    _, _, result = line_map
    mesh = dashes.build_mesh(result, RES, DASH)
    assert_printable(mesh)
    assert len(mesh.split(only_watertight=False)) == 1
    terrain = dashes.heightfield_solid(result.surface, RES, 0)
    assert mesh.volume > terrain.volume


def test_block_height_follows_the_profile(line_map):
    _, z, result = line_map
    taller = dashes.apply(z, RES, DASH.model_copy(update={"height_mm": 3.0}))
    assert [b.centre.tolist() for b in taller.blocks] == [b.centre.tolist() for b in result.blocks]
    for a, b in zip(result.blocks, taller.blocks, strict=True):
        assert b.top_mm - a.top_mm == pytest.approx(1.0)


def test_every_preset_has_dash_sizes():
    for name in ["fine", "standard", "coarse", "extra_coarse"]:
        assert load_profile(name).dashes is not None


# --- spec option and pipeline -------------------------------------------------------------


def _spec(**style) -> Spec:
    return Spec.model_validate(
        {
            "name": "d",
            "mode": "flat",
            "area": {"bbox": list(FIXTURE_BBOX)},
            "print": {"printer": "generic-220", "scale_m_per_mm": 15},
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
            "style": style,
        }
    )


def test_dashed_is_the_default_and_is_not_written_to_the_file(tmp_path):
    assert DEFAULT_LINE_RENDER == "dashed"
    assert _spec().style.line_render == "dashed"
    save_spec(_spec(), tmp_path / "a.json")
    assert "line_render" not in json.loads((tmp_path / "a.json").read_text())["style"]
    save_spec(_spec(line_render="solid"), tmp_path / "b.json")
    assert load_spec(tmp_path / "b.json").style.line_render == "solid"


def _heightfield(z):
    transform = PrintTransform.build(
        FIXTURE_BBOX, scale_m_per_mm=15, long_side_mm=None, z_exaggeration=1.0, base_mm=3.0,
        crs="EPSG:32613",
    )
    return stages.Heightfield(z, RES, transform)


def test_solid_lines_skip_the_dash_stage():
    ground, xx, yy = _ground()
    hf = _heightfield(_with_line(ground, yy, xx=xx))
    assert stages.dash(_spec(line_render="solid"), hf, None) is hf
    assert stages.dash(_spec(), hf, None).dash.blocks


def test_dash_cache_key_changes_with_the_option_and_the_sizes():
    stage = next(s for s in stages.STAGES if s.name == "dash")
    keys = {
        json.dumps(stage.spec_slice(spec, None))
        for spec in [
            _spec(),
            _spec(line_render="solid"),
            _spec(overrides={"dashes": {"gap_mm": 3.0}}),
        ]
    }
    assert len(keys) == 3
    names = [s.name for s in stages.STAGES]
    assert names.index("dash") == names.index("export") - 1


def test_dashed_export_keeps_to_the_stl_size_limit(tmp_path):
    ground, xx, yy = _ground(120.0, 80.0)
    hf = _heightfield(_with_line(ground, yy, xx=xx))
    hf = stages.dash(_spec(), hf, None)
    full = dashes.build_mesh(hf.dash, RES, DASH)
    limit = stl_size_mb(full) / 2
    printer = PrinterProfile(bed_mm=[220, 220, 250], nozzle_mm=0.4, grid_mm=RES, max_stl_mb=limit)
    ctx = stages.Context(tmp_path, printer)
    result = stages.export(_spec(), hf, ctx)
    assert result.size_mb <= limit
    assert result.decimated_tolerance_mm is not None


def test_no_block_means_the_solid_export(tmp_path):
    ground, _, _ = _ground()
    hf = stages.dash(_spec(), _heightfield(ground), None)
    assert hf.dash is not None and not hf.dash.blocks
    printer = PrinterProfile(bed_mm=[220, 220, 250], nozzle_mm=0.4, grid_mm=RES)
    dashed = stages.export(_spec(), hf, stages.Context(tmp_path / "a", printer))
    solid = stages.export(_spec(), replace(hf, dash=None), stages.Context(tmp_path / "b", printer))
    assert Path(dashed.path).read_bytes() == Path(solid.path).read_bytes()


# --- one offline build: toggle, undo, describe --------------------------------------------


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_toggle_and_undo_on_a_real_build(models_dir, offline_cache):
    shutil.copytree(FIXTURE_CACHE, models_dir / "wp" / "cache", dirs_exist_ok=True)
    api.create_model(
        "wp",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5, "base_mm": 3.0},
        features=[
            {
                "type": "road",
                "provider": "osm",
                "style": "flat_top",
                "filter": {"classes": ["primary"], "include_refs": ["US 40"]},
            }
        ],
    )
    stl = models_dir / "wp" / "wp.stl"
    dashed = _sha(stl)
    described = " ".join(api.describe_model("wp").split())  # undo line wrapping
    assert "Every line is drawn dashed" in described
    assert "2 mm long, 2 mm wide and 2 mm tall above the ground, 2 mm apart" in described
    assert "A block starts every 4 mm along each line" in described

    api.update_model("wp", {"style": {"line_render": "solid"}})
    assert _sha(stl) != dashed
    assert "drawn dashed" not in " ".join(api.describe_model("wp").split())

    api.update_model("wp", {"revert_to": "last"})
    assert _sha(stl) == dashed
    api.check_print("wp")
    notes = (models_dir / "wp" / "print-pack" / "PRINT-NOTES.txt").read_text(encoding="utf-8")
    assert "dashed lines of raised blocks" in notes
