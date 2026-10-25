import shutil
from pathlib import Path

import pytest

FIXTURE_CACHE = Path(__file__).parent / "fixtures" / "winter-park-cache"
FIXTURE_BBOX = (-105.780, 39.873, -105.745, 39.900)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Every test gets its own config directory."""
    monkeypatch.setenv("TACTILE_TERRAIN_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


@pytest.fixture
def offline_cache(tmp_path, monkeypatch):
    """The recorded Winter Park data as the download cache, with every network path broken."""
    from tactile_terrain.providers import http, nhd, usgs3dep
    from tactile_terrain.providers.cache import using_cache_dir

    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    cache = tmp_path / "download-cache"
    shutil.copytree(FIXTURE_CACHE, cache)
    monkeypatch.setattr(http.httpx, "request", no_network)
    monkeypatch.setattr(usgs3dep.Usgs3dep, "_download", no_network)
    monkeypatch.setattr(nhd.Nhd, "_download", no_network)
    with using_cache_dir(cache):
        yield cache
