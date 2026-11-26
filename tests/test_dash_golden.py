"""Golden tests for dashed lines on the Tilden sample (marked `golden`, run by scripts/verify_dash.py).

Acceptance:
- dashing off rebuilds the Tilden print-pack STL made before dashing existed;
- dashing on (the fork's default) matches dash-trails 1.0.0 run on that STL at the default height;
- the vendored dash-trails 1.0.0 oracle itself still gives the golden output on this machine.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest
import trimesh
from golden import assert_matches

from tactile_terrain.config import PrinterProfile
from tactile_terrain.pipeline.stages import run_pipeline
from tactile_terrain.providers import http, nhd, usgs3dep
from tactile_terrain.spec import load_spec

pytestmark = pytest.mark.golden

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"
ORACLE = Path(__file__).parent / "oracle" / "dash_trails_v1.py"
# The printer the Tilden sample was built for: 0.2 mm grid, no STL size limit.
BAMBU_A1_MINI = PrinterProfile(bed_mm=[180, 180, 180], nozzle_mm=0.4, grid_mm=0.2, bed_margin_mm=5)


def _oracle():
    spec = importlib.util.spec_from_file_location("dash_trails_v1", ORACLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def oracle_dash(stl: Path, height_mm: float) -> trimesh.Trimesh:
    """dash-trails 1.0.0's main(), with its defaults and the given block height."""
    dt = _oracle()
    defaults = {"height": height_mm, "width": 2.0, "length": 2.0, "gap": 2.0, "embed": 0.6}
    args = type("Args", (), defaults)
    heights, res, (x0, y0, zbase) = dt.load_heightmap(stl)
    band = dt.detect_trails(heights, res)
    cleaned = dt.remove_ridges(heights, band, res)
    blocks = dt.place_blocks(dt.centerlines(band, res), cleaned, res, args)
    mesh = dt.build_mesh(cleaned, res, zbase, blocks, args)
    mesh.apply_translation([x0, y0, 0])
    return mesh


@pytest.fixture(scope="module")
def tilden(tmp_path_factory):
    """Build Tilden offline from the recorded data. Returns build(style_changes) -> STL path."""
    root = tmp_path_factory.mktemp("tilden")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TACTILE_TERRAIN_CONFIG_DIR", str(root / "cfg"))

        def boom(*args, **kwargs):
            raise AssertionError("network access attempted")

        mp.setattr(http.httpx, "request", boom)
        mp.setattr(usgs3dep.Usgs3dep, "_download", boom)
        mp.setattr(nhd.Nhd, "_download", boom)

        def build(style: dict | None = None, folder: str = "model") -> Path:
            model_dir = root / folder
            if not model_dir.exists():
                shutil.copytree(FIXTURES / "tilden-cache", model_dir / "cache")
            spec = load_spec(GOLDEN / "tilden_spec.json")
            if style:
                spec = spec.model_copy(update={"style": spec.style.model_copy(update=style)})
            return Path(run_pipeline(spec, model_dir, BAMBU_A1_MINI)["export"].path)

        yield build


def _load(path: Path) -> trimesh.Trimesh:
    return trimesh.load(path, force="mesh")


def test_dash_off_rebuilds_the_pre_dash_print_pack(tilden):
    assert_matches(_load(tilden({"line_render": "solid"}, "off")), GOLDEN / "tilden_off", "dash off")


def test_oracle_on_rebuilt_mesh_matches_golden(tilden):
    stl = tilden({"line_render": "solid"}, "off")
    assert_matches(oracle_dash(stl, 2.0), GOLDEN / "tilden_dashed_2mm", "dash-trails 1.0.0 oracle")


def test_dash_on_is_the_default_and_matches_golden(tilden):
    assert_matches(_load(tilden(None, "default")), GOLDEN / "tilden_dashed_2mm", "default build")


def test_dash_height_comes_from_the_profile(tilden):
    stl = tilden({"overrides": {"dashes": {"height_mm": 1.0}}}, "one-mm")
    assert_matches(_load(stl), GOLDEN / "tilden_dashed_1mm", "1 mm override")
