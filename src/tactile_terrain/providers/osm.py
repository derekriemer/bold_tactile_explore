"""OpenStreetMap roads, aerialways and named points through one Overpass query per area."""

from __future__ import annotations

from typing import Any, ClassVar

from shapely.geometry import LineString

from tactile_terrain.config import load_config
from tactile_terrain.providers import http
from tactile_terrain.providers.base import BBox, LineFeature, NamedPoint, SourceInfo
from tactile_terrain.providers.cache import cache_path, read_json, write_json
from tactile_terrain.providers.names import name_matches
from tactile_terrain.registry import line_providers

ROAD_CLASSES = "motorway|trunk|primary|secondary|tertiary"
NOT_LINES = {"station", "pylon"}  # aerialway values that are not cables
POINT_KINDS = {"peak": "peak", "saddle": "saddle"}


def build_query(bbox: BBox) -> str:
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    return (
        "[out:json][timeout:180];("
        f'way["highway"~"^({ROAD_CLASSES})(_link)?$"]{area};'
        f'way["aerialway"]{area};'
        f'node["natural"~"^(peak|saddle)$"]{area};'
        f'node["mountain_pass"="yes"]{area};'
        ");out geom tags;"
    )


def _refs(tags: dict[str, str]) -> list[str]:
    return [r.strip() for r in tags.get("ref", "").split(";") if r.strip()]


class Osm:
    """Roads, ski lifts and named peaks from OpenStreetMap."""

    filters: ClassVar[dict[str, str]] = {
        "road": "classes (motorway, trunk, primary, secondary, tertiary), include_refs (refs always kept, for example US 40)",
        "lift": "aerialway (all, or a list of types), exclude (list of types to leave out)",
    }
    source = SourceInfo(
        name="OpenStreetMap",
        licence="ODbL 1.0",
        attribution="Roads, lifts and place names: (c) OpenStreetMap contributors, ODbL.",
    )

    def fetch(self, bbox: BBox, feature_type: str, filter: dict[str, Any]) -> list[LineFeature]:
        if feature_type == "road":
            return self._roads(bbox, filter)
        if feature_type == "lift":
            return self._lifts(bbox, filter)
        raise ValueError(f"osm provides 'road' and 'lift' features, not '{feature_type}'")

    def fetch_points(self, bbox: BBox) -> list[NamedPoint]:
        points = []
        for el in self._elements(bbox):
            tags = el.get("tags", {})
            if el["type"] != "node" or not tags.get("name"):
                continue
            kind = POINT_KINDS.get(tags.get("natural", ""))
            if tags.get("mountain_pass") == "yes":
                kind = "pass"
            if kind is None:
                continue
            ele = tags.get("ele", "").split()[0:1]
            try:
                elevation = float(ele[0]) if ele else None
            except ValueError:
                elevation = None
            points.append(NamedPoint(tags["name"], kind, el["lon"], el["lat"], elevation))
        return points

    def _elements(self, bbox: BBox) -> list[dict]:
        path = cache_path("osm", bbox, "json")
        cached = read_json(path)
        if cached is not None:
            return cached
        elements = self._download(bbox)
        write_json(path, elements)
        return elements

    def _download(self, bbox: BBox) -> list[dict]:
        response = http.request(
            "POST", load_config().overpass_endpoint, data={"data": build_query(bbox)}
        )
        return response.json()["elements"]

    def _ways(self, bbox: BBox, tag: str):
        for el in self._elements(bbox):
            tags = el.get("tags", {})
            if el["type"] == "way" and tag in tags and len(el.get("geometry", [])) >= 2:
                line = LineString([(p["lon"], p["lat"]) for p in el["geometry"]])
                yield el, tags, line

    def _roads(self, bbox: BBox, filter: dict[str, Any]) -> list[LineFeature]:
        classes = filter.get("classes")
        wanted_refs = filter.get("include_refs", [])
        out = []
        for el, tags, line in self._ways(bbox, "highway"):
            highway = tags["highway"]
            base = highway.removesuffix("_link")
            if (
                classes is None
                or highway in classes
                or base in classes
                or any(name_matches(r, wanted_refs) for r in _refs(tags))
            ):
                attrs = {"ref": tags.get("ref", ""), "osm_id": el["id"]}
                out.append(LineFeature(line, tags.get("name", ""), highway, attrs))
        return out

    def _lifts(self, bbox: BBox, filter: dict[str, Any]) -> list[LineFeature]:
        wanted = filter.get("aerialway", "all")
        excluded = set(filter.get("exclude", []))
        out = []
        for el, tags, line in self._ways(bbox, "aerialway"):
            kind = tags["aerialway"]
            if kind in NOT_LINES or kind in excluded:
                continue
            if wanted == "all" or kind in wanted:
                out.append(LineFeature(line, tags.get("name", ""), kind, {"osm_id": el["id"]}))
        return out


line_providers.register("osm", Osm())
