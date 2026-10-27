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
MINOR_CLASSES = ("unclassified", "residential", "service", "track")  # fetched only when asked for
NOT_LINES = {"station", "pylon"}  # aerialway values that are not cables
POINT_KINDS = {"peak": "peak", "saddle": "saddle"}


def build_query(bbox: BBox, minor: bool = False) -> str:
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    classes = "|".join([ROAD_CLASSES, *MINOR_CLASSES]) if minor else ROAD_CLASSES
    return (
        "[out:json][timeout:180];("
        f'way["highway"~"^({classes})(_link)?$"]{area};'
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
        "road": (
            "classes (motorway, trunk, primary, secondary, tertiary, and the minor unclassified, "
            "residential, service, track, which are only downloaded when asked for), include_refs and "
            "include_names (always kept, for example US 40 or Parsenn Road; a name also finds minor "
            "roads), exclude_refs and "
            "exclude_names (always dropped, applied last), named_only (true drops unnamed roads), "
            "merge_within_m (merge same-name parallel "
            "lines closer than this many metres, for divided roads)"
        ),
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

    def _elements(self, bbox: BBox, minor: bool = False) -> list[dict]:
        # Minor roads (service, track...) are a bigger download, so they get their own cache entry.
        path = cache_path("osm", bbox, "json", **({"minor_roads": True} if minor else {}))
        cached = read_json(path)
        if cached is not None:
            return cached
        elements = self._download(bbox, minor)
        write_json(path, elements)
        return elements

    def _download(self, bbox: BBox, minor: bool = False) -> list[dict]:
        response = http.request(
            "POST", load_config().overpass_endpoint, data={"data": build_query(bbox, minor)}
        )
        return response.json()["elements"]

    def _ways(self, bbox: BBox, tag: str, minor: bool = False):
        for el in self._elements(bbox, minor):
            tags = el.get("tags", {})
            if el["type"] == "way" and tag in tags and len(el.get("geometry", [])) >= 2:
                line = LineString([(p["lon"], p["lat"]) for p in el["geometry"]])
                yield el, tags, line

    def _roads(self, bbox: BBox, filter: dict[str, Any]) -> list[LineFeature]:
        classes = filter.get("classes")
        wanted_refs = filter.get("include_refs", [])
        wanted_names = filter.get("include_names", [])
        dropped_refs = filter.get("exclude_refs", [])
        dropped_names = filter.get("exclude_names", [])
        named_only = filter.get("named_only", False)
        wants_minor = any(c in MINOR_CLASSES for c in classes or []) or bool(wanted_names)
        out = []
        for el, tags, line in self._ways(bbox, "highway", wants_minor):
            highway = tags["highway"]
            base = highway.removesuffix("_link")
            if (
                classes is None
                or highway in classes
                or base in classes
                or any(name_matches(r, wanted_refs) for r in _refs(tags))
                or name_matches(tags.get("name", ""), wanted_names)
            ):
                if (
                    (named_only and not tags.get("name"))
                    or name_matches(tags.get("name", ""), dropped_names)
                    or any(name_matches(r, dropped_refs) for r in _refs(tags))
                ):
                    continue
                attrs = {"ref": tags.get("ref", ""), "osm_id": el["id"]}
                # A road with a route number but no name (US 40 outside town) goes by its number.
                name = tags.get("name") or (_refs(tags) or [""])[0]
                out.append(LineFeature(line, name, highway, attrs))
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
