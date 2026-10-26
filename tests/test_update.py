import json
import shutil

import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE

from tactile_terrain import api
from tactile_terrain.editing import apply_changes, diff_lines
from tactile_terrain.providers import http, nhd, usgs3dep

FEATURES = [
    {
        "type": "river",
        "provider": "nhd",
        "style": "rounded_major",
        "filter": {"min_stream_order": 4, "include_names": ["Fraser River"]},
    },
    {
        "type": "lift",
        "provider": "osm",
        "style": "pointed",
        "filter": {"aerialway": "all", "exclude": ["magic_carpet"]},
    },
]


@pytest.fixture
def model(models_dir, monkeypatch):
    shutil.copytree(FIXTURE_CACHE, models_dir / "m" / "cache", dirs_exist_ok=True)

    def boom(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(http.httpx, "request", boom)
    monkeypatch.setattr(usgs3dep.Usgs3dep, "_download", boom)
    monkeypatch.setattr(nhd.Nhd, "_download", boom)
    api.create_model(
        "m",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5, "base_mm": 3.0},
        features=FEATURES,
    )
    return models_dir / "m"


def spec_of(folder):
    return json.loads((folder / "spec.json").read_text(encoding="utf-8"))


def test_z_multiply_doubles_exaggeration_and_reports_before_and_after(model):
    text = api.update_model("m", {"z_multiply": 2})
    assert "print.z_exaggeration: 1.5 → 3.0" in text
    assert spec_of(model)["print"]["z_exaggeration"] == 3.0
    assert json.loads((model / "spec.1.json").read_text(encoding="utf-8"))["print"][
        "z_exaggeration"
    ] == pytest.approx(1.5)
    assert "Built model" in text and "Analysis:" in text


def test_drop_feature_removes_that_type(model):
    api.update_model("m", {"drop_feature": "lift"})
    assert [f["type"] for f in spec_of(model)["features"]] == ["river"]


def test_drop_feature_with_no_match_lists_the_types(model):
    with pytest.raises(ValueError, match="lift, river"):
        api.update_model("m", {"drop_feature": "trail"})


def test_merge_patch_changes_a_nested_value(model):
    text = api.update_model("m", {"print": {"base_mm": 4.0}})
    assert "print.base_mm: 3.0 → 4.0" in text and spec_of(model)["print"]["base_mm"] == 4.0


def test_revert_to_first_version_restores_the_spec_exactly(model):
    original = (model / "spec.json").read_bytes()
    api.update_model("m", {"z_multiply": 2})
    api.update_model("m", {"revert_to": 1})
    assert (model / "spec.json").read_bytes() == original
    assert (model / "spec.1.json").read_bytes() == original
    assert (model / "spec.2.json").exists()  # the doubled version was kept too


def test_invalid_patch_leaves_spec_unchanged_and_names_the_bad_key(model):
    before = (model / "spec.json").read_bytes()
    with pytest.raises(ValueError, match="wobble"):
        api.update_model("m", {"print": {"wobble": 1}})
    assert (model / "spec.json").read_bytes() == before
    assert not (model / "spec.1.json").exists()


def test_unknown_style_is_rejected_with_valid_names(model):
    before = (model / "spec.json").read_bytes()
    with pytest.raises(ValueError, match="rounded_major"):
        api.update_model("m", {"features": [{**FEATURES[0], "style": "nope"}]})
    assert (model / "spec.json").read_bytes() == before


def test_no_change_does_not_rebuild_or_back_up(model):
    text = api.update_model("m", {"print": {"base_mm": 3.0}})
    assert text.startswith("No change") and not (model / "spec.1.json").exists()


def test_unknown_model_lists_existing_models(model):
    with pytest.raises(FileNotFoundError, match="m"):
        api.update_model("missing", {"z_multiply": 2})


def test_crop_percent_moves_edges_inward(tmp_path):
    current = {"area": {"bbox": [-105.0, 39.0, -104.0, 40.0]}, "print": {}}
    new = apply_changes(current, {"crop_percent": {"east": 10, "north": 25}}, tmp_path)
    assert new["area"]["bbox"] == pytest.approx([-105.0, 39.0, -104.1, 39.75])


def test_crop_percent_rejects_bad_edges_and_amounts(tmp_path):
    current = {"area": {"bbox": [0, 0, 1, 1]}, "print": {}}
    with pytest.raises(ValueError, match="up"):
        apply_changes(current, {"crop_percent": {"up": 5}}, tmp_path)
    with pytest.raises(ValueError, match="some area"):
        apply_changes(current, {"crop_percent": {"east": 60, "west": 40}}, tmp_path)


def test_diff_lines_shows_added_and_removed_keys():
    lines = diff_lines({"a": {"b": 1}, "c": 2}, {"a": {"b": 2}, "d": 3})
    assert lines == ["a.b: 1 → 2", "c: 2 → (none)", "d: (none) → 3"]


def test_description_file_follows_the_edit(model):
    assert "exaggeration: 1.5 times" in (model / "DESCRIPTION.md").read_text(encoding="utf-8")
    api.update_model("m", {"z_multiply": 2})
    assert "exaggeration: 3 times" in (model / "DESCRIPTION.md").read_text(encoding="utf-8")


def test_revert_to_last_undoes_the_latest_edit_and_runs_again_to_redo_it(model):
    api.update_model("m", {"z_multiply": 2})
    api.update_model("m", {"revert_to": "last"})
    assert spec_of(model)["print"]["z_exaggeration"] == 1.5
    api.update_model("m", {"revert_to": "last"})
    assert spec_of(model)["print"]["z_exaggeration"] == 3.0


def test_revert_to_last_with_no_edits_says_nothing_to_undo(model):
    with pytest.raises(FileNotFoundError, match="Nothing to undo"):
        api.update_model("m", {"revert_to": "last"})


def test_history_lists_versions_and_what_changed(model):
    assert "has not been edited" in api.model_history("m")
    api.update_model("m", {"z_multiply": 2})
    api.update_model("m", {"print": {"base_mm": 4.0}})
    text = api.model_history("m")
    assert "Version 1: the first spec." in text and "Version 2:" in text and "Current:" in text
    assert "print.z_exaggeration: 1.5 → 3.0" in text and "print.base_mm: 3.0 → 4.0" in text
    assert "revert_to" in text
