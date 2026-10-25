import json
import shutil

import pytest
import trimesh
from conftest import FIXTURE_BBOX, FIXTURE_CACHE
from helpers import assert_printable

from tactile_terrain import api
from tactile_terrain.providers import http, nhd, usgs3dep
from tactile_terrain.spec import load_spec

FEATURES = [
    {
        "type": "river",
        "provider": "nhd",
        "style": "rounded_major",
        "filter": {"min_stream_order": 4, "include_names": ["Fraser River"]},
    },
    {
        "type": "road",
        "provider": "osm",
        "style": "flat_top",
        "filter": {"classes": ["primary"], "include_refs": ["US 40"]},
    },
    {
        "type": "lift",
        "provider": "osm",
        "style": "pointed",
        "filter": {"aerialway": "all", "exclude": ["magic_carpet"]},
    },
]


def _build(models_dir, name, mode):
    shutil.copytree(FIXTURE_CACHE, models_dir / name / "cache", dirs_exist_ok=True)
    return api.create_model(
        name,
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5, "base_mm": 3.0},
        mode=mode,
        features=FEATURES,
        style={"tactile_profile": "standard"},
    )


def _no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("provider called the network")

    monkeypatch.setattr(http.httpx, "request", boom)
    monkeypatch.setattr(usgs3dep.Usgs3dep, "_download", boom)
    monkeypatch.setattr(nhd.Nhd, "_download", boom)


@pytest.mark.parametrize("mode", ["terrain", "flat"])
def test_fixture_area_builds_printable_stl(models_dir, monkeypatch, mode):
    _no_network(monkeypatch)
    summary = _build(models_dir, f"wp-{mode}", mode)
    folder = models_dir / f"wp-{mode}"
    assert f"Built model 'wp-{mode}'" in summary and "mm" in summary
    assert_printable(trimesh.load(folder / f"wp-{mode}.stl"))
    attribution = (folder / "ATTRIBUTION.txt").read_text(encoding="utf-8")
    assert "USGS" in attribution and "OpenStreetMap" in attribution
    assert json.loads((folder / "spec.json").read_text(encoding="utf-8"))["mode"] == mode


def test_rebuild_with_no_changes_makes_no_provider_calls(models_dir, monkeypatch):
    _no_network(monkeypatch)
    _build(models_dir, "again", "terrain")
    calls = []
    for cls in (usgs3dep.Usgs3dep, nhd.Nhd):
        original = cls.fetch

        def counting(self, *args, _original=original, **kwargs):
            calls.append(1)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "fetch", counting)
    api.build_spec(load_spec(models_dir / "again" / "spec.json"), overwrite=True)
    assert calls == []


def test_existing_model_is_not_overwritten_silently(models_dir):
    _build(models_dir, "dup", "flat")
    with pytest.raises(FileExistsError, match="update_model"):
        _build(models_dir, "dup", "flat")
