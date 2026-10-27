"""NHDPlus flowlines (rivers and streams) through pynhd: HR first, medium resolution as fallback."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import shapely
from shapely.geometry import mapping, shape

from tactile_terrain.providers.base import BBox, LineFeature, SourceInfo
from tactile_terrain.providers.cache import cache_path, read_json, write_json
from tactile_terrain.providers.names import name_matches
from tactile_terrain.registry import line_providers

STREAM_FTYPES = {"StreamRiver", "ArtificialPath"}  # the latter runs through lakes and wide rivers
HR_FTYPE_CODES = {460: "StreamRiver", 558: "ArtificialPath"}  # HR gives codes, V2 gives names
HR_TILE_DEG = 0.08  # the HR service rejects large queries, so ask for tiles of this size


def _ftype(value: Any) -> str:
    return HR_FTYPE_CODES.get(value, str(value)) if isinstance(value, (int, float)) else str(value)


def _tiles(bbox: BBox) -> list[BBox]:
    west, south, east, north = bbox
    nx = max(1, math.ceil((east - west) / HR_TILE_DEG))
    ny = max(1, math.ceil((north - south) / HR_TILE_DEG))
    xs = [west + (east - west) * i / nx for i in range(nx + 1)]
    ys = [south + (north - south) * j / ny for j in range(ny + 1)]
    return [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for j in range(ny) for i in range(nx)]


def _clean_name(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _to_features(gdf, dataset: str) -> list[LineFeature]:
    out = []
    for _, row in gdf.iterrows():
        ftype = _ftype(row["ftype"])
        if ftype not in STREAM_FTYPES or row.geometry is None:
            continue
        out.append(
            LineFeature(
                geometry=shapely.force_2d(row.geometry),
                name=_clean_name(row.get("gnis_name")),
                kind="stream",
                attrs={
                    "stream_order": int(row["streamorde"]),
                    "ftype": ftype,
                    "dataset": dataset,
                },
            )
        )
    return out


class Nhd:
    """Rivers and streams from the National Hydrography Dataset Plus."""

    filters: ClassVar[dict[str, str]] = {
        "river": "min_stream_order (whole number: streams of at least that order are kept), include_names (names kept even below that order; on its own it restricts nothing), named_only (true drops every unnamed stream)",
        "creek": "min_stream_order (whole number: streams of at least that order are kept), include_names (names kept even below that order; on its own it restricts nothing), named_only (true drops every unnamed stream)",
    }
    source = SourceInfo(
        name="USGS National Hydrography Dataset Plus (NHDPlus)",
        licence="Public domain",
        attribution="Rivers and streams: U.S. Geological Survey, National Hydrography Dataset Plus.",
    )

    def fetch(self, bbox: BBox, feature_type: str, filter: dict[str, Any]) -> list[LineFeature]:
        features = self._all(bbox)
        min_order = filter.get("min_stream_order", 0)
        names = filter.get("include_names", [])
        named_only = filter.get("named_only", False)
        return [
            f
            for f in features
            if (f.name or not named_only)
            and (f.attrs["stream_order"] >= min_order or name_matches(f.name, names))
        ]

    def _all(self, bbox: BBox) -> list[LineFeature]:
        path = cache_path("nhd", bbox, "json")
        cached = read_json(path)
        if cached is not None:
            return [
                LineFeature(shape(item["geometry"]), item["name"], item["kind"], item["attrs"])
                for item in cached
            ]
        features = self._download(bbox)
        write_json(
            path,
            [
                {"geometry": mapping(f.geometry), "name": f.name, "kind": f.kind, "attrs": f.attrs}
                for f in features
            ],
        )
        return features

    def _download(self, bbox: BBox) -> list[LineFeature]:
        import pynhd

        try:
            seen: set[str] = set()
            features: list[LineFeature] = []
            for tile in _tiles(bbox):
                gdf = pynhd.NHDPlusHR("flowline").bygeom(tile)
                gdf = gdf[~gdf["nhdplusid"].astype(str).isin(seen)]
                seen.update(gdf["nhdplusid"].astype(str))
                features += _to_features(gdf, "NHDPlus HR")
            return features
        except Exception:  # noqa: BLE001  (any HR service failure falls back to NHDPlus V2)
            gdf = pynhd.WaterData("nhdflowline_network").bybox(bbox)
            return _to_features(gdf, "NHDPlus V2")


line_providers.register("nhd", Nhd())
