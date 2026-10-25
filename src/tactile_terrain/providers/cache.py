"""Download cache: provider data keyed by provider, bbox (rounded) and request parameters.

A cache hit makes no network call. The pipeline points the cache at `<model>/cache/`;
otherwise it lives under the user config directory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tactile_terrain.config import config_dir

BBOX_DECIMALS = 5  # 1e-5 degrees, about 1 m

_cache_dir: Path | None = None


def get_cache_dir() -> Path:
    path = _cache_dir if _cache_dir is not None else config_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def using_cache_dir(path: str | Path) -> Iterator[Path]:
    global _cache_dir
    previous, _cache_dir = _cache_dir, Path(path)
    try:
        yield _cache_dir
    finally:
        _cache_dir = previous


def cache_path(provider: str, bbox: tuple[float, ...] | None, suffix: str, **params: Any) -> Path:
    rounded = None if bbox is None else [round(float(v), BBOX_DECIMALS) for v in bbox]
    payload = json.dumps([provider, rounded, params], sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return get_cache_dir() / f"{provider}-{digest}.{suffix}"


def read_json(path: Path) -> Any | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
