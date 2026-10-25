import re
import shutil

import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE

from tactile_terrain import api


@pytest.fixture
def model(models_dir):
    shutil.copytree(FIXTURE_CACHE, models_dir / "m" / "cache", dirs_exist_ok=True)
    api.create_model(
        "m",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5},
        mode="flat",
        features=[
            {"type": "lift", "provider": "osm", "style": "pointed", "filter": {"aerialway": "all"}}
        ],
    )
    return models_dir / "m"


def test_print_pack_has_every_file_with_the_right_contents(model, monkeypatch):
    from tactile_terrain import printpack

    monkeypatch.setattr(printpack.shutil, "which", lambda name: None)
    text = api.check_print("m")
    pack = model / "print-pack"
    assert {p.name for p in pack.iterdir()} == {
        "m.stl",
        "ATTRIBUTION.txt",
        "PRINT-NOTES.txt",
        "SUBMIT-NOTES.txt",
        "DESCRIPTION.md",
    }
    notes = (pack / "PRINT-NOTES.txt").read_text(encoding="utf-8")
    assert "mm by" in notes and "no supports" in notes and "solid mass" in notes
    submit = (pack / "SUBMIT-NOTES.txt").read_text(encoding="utf-8")
    assert "Request via the library form. One colour. Up to 10 days." in submit
    assert "blind user" in submit
    assert "Print time: unavailable" in text and "limit is 8 hours" in text
    assert "watertight yes" in text and "Print pack written to" in text


def test_printer_without_submit_notes_gets_no_submit_file(models_dir):
    shutil.copytree(FIXTURE_CACHE, models_dir / "g" / "cache", dirs_exist_ok=True)
    api.create_model(
        "g",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "printer": "generic-220"},
        mode="flat",
    )
    api.check_print("g")
    assert not (models_dir / "g" / "print-pack" / "SUBMIT-NOTES.txt").exists()


def test_stl_size_limit_thins_flat_areas_in_the_export(models_dir):
    from tactile_terrain.config import config_path

    path = config_path()
    path.write_text(re.sub(r"max_stl_mb = 0(\.0)?", "max_stl_mb = 2", path.read_text(), count=1))
    shutil.copytree(FIXTURE_CACHE, models_dir / "s" / "cache", dirs_exist_ok=True)
    api.create_model(
        "s", area=list(FIXTURE_BBOX), print={"scale_m_per_mm": 15, "base_mm": 3.0}, mode="flat"
    )
    stl = models_dir / "s" / "s.stl"
    assert stl.stat().st_size <= 2 * 1_000_000
    assert "flat areas thinned" in api.check_print("s")


def test_every_model_folder_has_a_text_description(model):
    text = (model / "DESCRIPTION.md").read_text(encoding="utf-8")
    assert text == api.describe_model("m")
    assert "Orientation" in text and "Tactile legend" in text
    api.check_print("m")
    assert (model / "print-pack" / "DESCRIPTION.md").read_text(encoding="utf-8") == text
