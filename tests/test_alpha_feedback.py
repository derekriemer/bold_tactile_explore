"""Changes made from an alpha tester's notes: road names, previews, brief output, clean failures."""

import httpx
import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE
from shapely.geometry import LineString

from tactile_terrain import api
from tactile_terrain.pipeline.stages import merge_parallels
from tactile_terrain.providers import http, nhd, usgs3dep
from tactile_terrain.providers.osm import Osm


def way(osm_id, highway, name, ref, coords):
    tags = {"highway": highway, "name": name}
    if ref:
        tags["ref"] = ref
    geometry = [{"lon": x, "lat": y} for x, y in coords]
    return {"type": "way", "id": osm_id, "tags": tags, "geometry": geometry}


ELEMENTS = [
    way(1, "primary", "Broadway", "CO 93", [(0, 0), (0, 1)]),
    way(2, "tertiary", "Baseline Road", "CR 56", [(0, 0), (1, 0)]),
    way(3, "tertiary", "Table Mesa Drive", "", [(1, 1), (2, 1)]),
    way(4, "secondary", "Moorhead Avenue", "", [(2, 2), (3, 2)]),
]


@pytest.fixture
def osm(monkeypatch):
    provider = Osm()
    monkeypatch.setattr(provider, "_elements", lambda bbox: ELEMENTS)
    return provider


def names(features):
    return sorted(f.name for f in features)


def test_roads_can_be_kept_by_name_beyond_their_class(osm):
    kept = osm.fetch(
        (0, 0, 3, 3), "road", {"classes": ["primary"], "include_names": ["Baseline Road"]}
    )
    assert names(kept) == ["Baseline Road", "Broadway"]


def test_roads_can_be_dropped_by_name_or_ref(osm):
    box = (0, 0, 3, 3)
    assert "Moorhead Avenue" not in names(
        osm.fetch(box, "road", {"exclude_names": ["Moorhead Avenue"]})
    )
    assert "Broadway" not in names(osm.fetch(box, "road", {"exclude_refs": ["CO 93"]}))


def test_exclusion_wins_over_inclusion(osm):
    kept = osm.fetch(
        (0, 0, 3, 3), "road", {"include_names": ["Broadway"], "exclude_names": ["Broadway"]}
    )
    assert "Broadway" not in names(kept)


def test_merge_parallels_keeps_one_of_two_carriageways():
    long_side = LineString([(0, 0), (100, 0)])
    other_side = LineString([(0, 0.5), (95, 0.5)])
    far_branch = LineString([(0, 50), (30, 50)])
    kept = merge_parallels([other_side, long_side, far_branch], 1.0)
    assert sum(g.length for g in kept) == pytest.approx(130.0)
    assert long_side in kept


def test_a_data_service_outage_is_a_plain_message(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        http.httpx,
        "request",
        lambda *a, **k: httpx.Response(
            502, request=httpx.Request("POST", "https://overpass-api.de/x")
        ),
    )
    with pytest.raises(http.DataServiceError, match="no key"):
        http.request("POST", "https://overpass-api.de/api/interpreter")


def test_a_failed_new_build_leaves_no_model_behind(models_dir, monkeypatch):
    def boom(*args, **kwargs):
        raise http.DataServiceError("Overpass did not answer")

    monkeypatch.setattr(Osm, "_download", boom)
    monkeypatch.setattr(usgs3dep.Usgs3dep, "_download", boom)
    monkeypatch.setattr(nhd.Nhd, "_download", boom)
    spec = {"area": list(FIXTURE_BBOX), "print": {"scale_m_per_mm": 15}}
    with pytest.raises(http.DataServiceError):
        api.create_model("broken", features=[], **spec)
    assert not (models_dir / "broken" / "spec.json").exists()
    assert "broken" not in api.list_models()


@pytest.fixture
def model(models_dir, monkeypatch):
    import shutil

    shutil.copytree(FIXTURE_CACHE, models_dir / "m" / "cache", dirs_exist_ok=True)

    def boom(*args, **kwargs):
        raise AssertionError("network access attempted")

    for target in (http.httpx,):
        monkeypatch.setattr(target, "request", boom)
    monkeypatch.setattr(usgs3dep.Usgs3dep, "_download", boom)
    monkeypatch.setattr(nhd.Nhd, "_download", boom)
    api.create_model(
        "m",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5, "base_mm": 3.0},
        features=[
            {"type": "road", "provider": "osm", "style": "flat_top",
             "filter": {"classes": ["primary"], "include_refs": ["US 40"]}},
        ],
    )  # fmt: skip
    return models_dir / "m"


def test_preview_lists_kept_and_left_out_lines_and_changes_nothing(model):
    before = (model / "spec.json").read_bytes()
    text = api.preview_features(name="m")
    assert "Nothing was built or changed" in text
    assert "Keeps" in text and "Leaves out" in text and "km" in text
    assert (model / "spec.json").read_bytes() == before


def test_brief_description_is_short_and_points_to_the_full_one(model):
    brief = api.describe_model("m", brief=True)
    full = api.describe_model("m")
    assert (
        "## Overview" in brief
        and "## Warnings and checks" in brief
        and "## Tactile legend" in brief
    )
    assert "## Cross-sections" not in brief and "## Line features" not in brief
    assert len(brief) < len(full) / 2


def test_ref_listing_names_the_road_each_ref_belongs_to(offline_cache):
    text = api.resolve_area(bbox=list(FIXTURE_BBOX))
    assert " = " in text  # refs are listed as "US 40 = Name"
