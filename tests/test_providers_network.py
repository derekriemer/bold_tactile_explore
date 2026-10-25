"""Hits the real services. Run with: uv run pytest -m network -q"""

import numpy as np
import pytest

from tactile_terrain import api  # noqa: F401  (registers providers)
from tactile_terrain.registry import elevation_providers, line_providers

WINTER_PARK = (-105.86, 39.79, -105.71, 39.96)

pytestmark = pytest.mark.network


def test_winter_park_data():
    grid = elevation_providers.get("usgs3dep").fetch(WINTER_PARK, 90)
    assert 2500 < np.nanmin(grid.data) and np.nanmax(grid.data) < 4200

    rivers = line_providers.get("nhd").fetch(WINTER_PARK, "river", {"min_stream_order": 4})
    assert "Fraser River" in {f.name for f in rivers}

    osm = line_providers.get("osm")
    roads = osm.fetch(WINTER_PARK, "road", {"classes": ["primary"]})
    assert any("US 40" in f.attrs["ref"] for f in roads)
    assert len(osm.fetch(WINTER_PARK, "lift", {"aerialway": "all"})) >= 10
