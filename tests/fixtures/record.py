"""Record the Winter Park fixture (needs network). Run: uv run python tests/fixtures/record.py

Runs resolve_area and the provider fetches the tests use, with the download cache pointed at
tests/fixtures/winter-park-cache/, so the committed files are exactly what the providers read.
"""

from pathlib import Path

from tactile_terrain import api
from tactile_terrain.providers.cache import using_cache_dir
from tactile_terrain.registry import elevation_providers, line_providers

# About 3 x 3 km around the Winter Park base area.
BBOX = (-105.780, 39.873, -105.745, 39.900)
OUT = Path(__file__).parent / "winter-park-cache"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with using_cache_dir(OUT):
        print(api.resolve_area(bbox=BBOX))
        elevation_providers.get("usgs3dep").fetch(BBOX, 10)
        line_providers.get("nhd").fetch(BBOX, "river", {})
        osm = line_providers.get("osm")
        osm.fetch(BBOX, "road", {})
    total = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"\nRecorded {len(list(OUT.iterdir()))} files, {total / 1024:.0f} KiB, in {OUT}")


if __name__ == "__main__":
    main()
