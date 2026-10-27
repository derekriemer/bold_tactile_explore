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
    monkeypatch.setattr(provider, "_elements", lambda bbox, minor=False: ELEMENTS)
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


def test_a_road_with_a_route_number_but_no_name_goes_by_its_number(osm, monkeypatch):
    monkeypatch.setattr(
        osm,
        "_elements",
        lambda bbox, minor=False: [way(9, "primary", "", "US 40", [(0, 0), (1, 1)])],
    )
    assert names(osm.fetch((0, 0, 3, 3), "road", {"classes": ["primary"]})) == ["US 40"]


def test_minor_roads_are_only_downloaded_when_asked_for(osm, monkeypatch):
    asked = []

    def elements(bbox, minor=False):
        asked.append(minor)
        return ELEMENTS

    monkeypatch.setattr(osm, "_elements", elements)
    osm.fetch((0, 0, 3, 3), "road", {"classes": ["primary"], "include_refs": ["US 40"]})
    osm.fetch((0, 0, 3, 3), "road", {"classes": ["primary", "service"]})
    osm.fetch((0, 0, 3, 3), "road", {"classes": ["primary"], "include_names": ["Parsenn Road"]})
    assert asked == [False, True, True]


# --- second round of notes ----------------------------------------------------------------


def test_list_changes_are_reported_by_field_and_item():
    from tactile_terrain.editing import diff_lines

    old = {"features": [{"type": "creek", "filter": {"include_names": ["A"], "order": 3}}]}
    new = {"features": [{"type": "creek", "filter": {"include_names": ["A", "B"], "order": 3}}]}
    assert diff_lines(old, new) == ['features[0].filter.include_names: added "B"']


def test_history_shows_the_reason_given_for_an_edit(model):
    api.update_model("m", {"z_multiply": 2}, reason="peaks looked flat")
    assert "Reason given: peaks looked flat" in api.model_history("m")


def test_update_reports_how_the_lines_changed(model):
    text = api.update_model(
        "m",
        {
            "features": [
                {
                    "type": "road",
                    "provider": "osm",
                    "style": "flat_top",
                    "filter": {"classes": ["motorway"]},
                }
            ]
        },
    )
    assert "Line changes:" in text


def test_named_only_drops_unnamed_streams(monkeypatch):
    from tactile_terrain.providers.base import LineFeature

    streams = [
        LineFeature(LineString([(0, 0), (1, 1)]), "Gregory Creek", "stream", {"stream_order": 1}),
        LineFeature(LineString([(0, 0), (1, 2)]), "", "stream", {"stream_order": 5}),
    ]
    provider = nhd.Nhd()
    monkeypatch.setattr(provider, "_all", lambda bbox: streams)
    kept = provider.fetch(
        (0, 0, 1, 1), "creek", {"include_names": ["Gregory Creek"], "named_only": True}
    )
    assert [f.name for f in kept] == ["Gregory Creek"]


def test_brief_description_honours_requested_sections_with_real_elevations(model):
    text = api.describe_model("m", sections=[{"x_mm": 40}], brief=True)
    assert "Requested cross-sections" in text and "North-south section at x = 40 mm" in text
    assert " m)" in text  # each height is followed by its elevation


def test_merge_parallels_keeps_bends_and_side_roads_whole():
    bend = [LineString([(0, 0), (50, 0)]), LineString([(50, 0), (50, 50)])]  # one road, one bend
    side = LineString([(25, 0), (25, 40)])  # leaves at right angles from the road
    merged = merge_parallels([*bend, side], 2.0)
    assert sum(g.length for g in merged) == pytest.approx(140.0, abs=2.0)


def test_merge_parallels_collapses_a_divided_road_but_not_its_bend():
    one_side = LineString([(0, 0), (60, 0), (60, 60)])
    other_side = LineString([(0, 1.5), (58.5, 1.5), (58.5, 60)])
    merged = merge_parallels([one_side, other_side], 3.0)
    assert sum(g.length for g in merged) == pytest.approx(120.0, abs=6.0)


def test_analyzer_flags_a_divided_road_and_offers_the_merge(model):
    from shapely.geometry import MultiLineString

    from tactile_terrain.analyzers import AnalysisContext
    from tactile_terrain.analyzers.spacing import Spacing
    from tactile_terrain.compose import PlacedLine
    from tactile_terrain.config import load_config
    from tactile_terrain.pipeline.stages import run_pipeline
    from tactile_terrain.spec import load_spec
    from tactile_terrain.styles import resolve_style
    from tactile_terrain.tactile.profile import load_profile

    cfg = load_config()
    spec = load_spec(model / "spec.json")
    hf = run_pipeline(spec, model, cfg.printer(spec.print.printer))["lines"]
    style = resolve_style("flat_top", load_profile("standard"))
    twin = MultiLineString([[(10, 10), (60, 10)], [(10, 11), (60, 11)]])
    hf.lines.append(PlacedLine("Broadway", "road", style, twin))
    ctx = AnalysisContext(spec, load_profile("standard"), cfg.printer(spec.print.printer), hf, None)
    found = [s for s in Spacing().analyze(ctx).suggestions if "Broadway" in s.message]
    assert found and "merge_within_m" in str(found[0].patch)
