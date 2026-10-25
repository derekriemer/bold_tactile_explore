"""Place-name lookup through Nominatim, cached. Used only by resolve_area(place)."""

from __future__ import annotations

from dataclasses import dataclass

from tactile_terrain.providers import http
from tactile_terrain.providers.base import BBox
from tactile_terrain.providers.cache import cache_path, read_json, write_json

ENDPOINT = "https://nominatim.openstreetmap.org/search"


@dataclass
class Place:
    display_name: str
    lon: float
    lat: float
    bbox: BBox


def geocode(place: str) -> Place:
    path = cache_path("nominatim", None, "json", place=place.strip().lower())
    data = read_json(path)
    if data is None:
        response = http.request("GET", ENDPOINT, params={"q": place, "format": "json", "limit": 1})
        results = response.json()
        if not results:
            raise ValueError(f"No place found for '{place}'. Try a more specific name or a bbox.")
        data = results[0]
        write_json(path, data)
    south, north, west, east = (float(v) for v in data["boundingbox"])
    return Place(
        data["display_name"], float(data["lon"]), float(data["lat"]), (west, south, east, north)
    )
