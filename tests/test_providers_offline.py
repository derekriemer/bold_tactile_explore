import numpy as np
import pytest
from conftest import FIXTURE_BBOX

from tactile_terrain import providers  # noqa: F401
from tactile_terrain.providers import http
from tactile_terrain.providers.names import name_matches, normalise_name
from tactile_terrain.registry import elevation_providers, line_providers


def test_elevation_from_cache(offline_cache):
    grid = elevation_providers.get("usgs3dep").fetch(FIXTURE_BBOX, 10)
    assert grid.data.ndim == 2 and grid.data.size > 10_000
    assert 2500 < np.nanmin(grid.data) < np.nanmax(grid.data) < 4200
    assert grid.crs.startswith("EPSG:")


def test_nhd_from_cache_and_stream_order_filter(offline_cache):
    nhd = line_providers.get("nhd")
    everything = nhd.fetch(FIXTURE_BBOX, "river", {})
    big = nhd.fetch(FIXTURE_BBOX, "river", {"min_stream_order": 4})
    assert everything and 0 < len(big) < len(everything)
    assert all(f.attrs["stream_order"] >= 4 for f in big)
    assert {f.name for f in big} >= {"Fraser River"}


def test_include_names_overrides_order_and_matches_abbreviations(offline_cache):
    nhd = line_providers.get("nhd")
    only_high = nhd.fetch(FIXTURE_BBOX, "river", {"min_stream_order": 5})
    assert "Jim Creek" not in {f.name for f in only_high}
    with_name = nhd.fetch(
        FIXTURE_BBOX, "creek", {"min_stream_order": 5, "include_names": ["jim ck"]}
    )
    assert "Jim Creek" in {f.name for f in with_name}
    assert all(f.name == "Jim Creek" or f.attrs["stream_order"] >= 5 for f in with_name)


def test_osm_roads_by_class_and_ref(offline_cache):
    osm = line_providers.get("osm")
    primary = osm.fetch(FIXTURE_BBOX, "road", {"classes": ["primary"]})
    assert primary and all(f.kind.startswith("primary") for f in primary)
    by_ref = osm.fetch(FIXTURE_BBOX, "road", {"classes": ["motorway"], "include_refs": ["US 40"]})
    assert by_ref and all("US 40" in f.attrs["ref"] for f in by_ref)


def test_osm_lifts_all_and_exclusions(offline_cache):
    osm = line_providers.get("osm")
    every = osm.fetch(FIXTURE_BBOX, "lift", {"aerialway": "all"})
    no_carpets = osm.fetch(FIXTURE_BBOX, "lift", {"aerialway": "all", "exclude": ["magic_carpet"]})
    assert any(f.kind == "magic_carpet" for f in every)
    assert no_carpets and not any(f.kind == "magic_carpet" for f in no_carpets)
    assert {f.kind for f in osm.fetch(FIXTURE_BBOX, "lift", {"aerialway": ["gondola"]})} == {
        "gondola"
    }


def test_osm_rejects_unknown_feature_type(offline_cache):
    with pytest.raises(ValueError, match="road"):
        line_providers.get("osm").fetch(FIXTURE_BBOX, "river", {})


def test_name_normalisation():
    assert normalise_name("Second Ck.") == "second creek"
    assert name_matches("Second Creek", ["second ck"])
    assert name_matches("Mt. Epworth", ["Mount Epworth"])
    assert not name_matches("", [""])
    assert not name_matches("Vasquez Creek", ["Second Creek"])


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_http_retries_on_429_and_504_with_user_agent(monkeypatch):
    calls = []
    statuses = iter([429, 504, 200])

    def fake_request(method, url, headers, **kwargs):
        calls.append(headers["User-Agent"])
        return _Response(next(statuses))

    monkeypatch.setattr(http.httpx, "request", fake_request)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert http.request("GET", "https://example.test/x").status_code == 200
    assert len(calls) == 3 and calls[0].startswith("tactile-terrain/")
