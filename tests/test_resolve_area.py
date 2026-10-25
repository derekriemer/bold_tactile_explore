import re

from conftest import FIXTURE_BBOX

from tactile_terrain import api


def test_report_from_fixtures(offline_cache):
    text = api.resolve_area(bbox=FIXTURE_BBOX)
    assert "west -105.78000" in text and "north 39.90000" in text
    assert re.search(r"\d+\.\d km east-west by \d+\.\d km north-south", text)
    assert re.search(r"\d+ m to \d+ m", text)
    assert "EPSG:32613" in text
    assert "Fraser River" in text  # a named stream
    assert "Arrow" in text and "chair_lift" in text  # a named lift
    assert "US 40" in text  # a road ref
    assert not re.search(r"image|picture|png|jpg|screenshot", text, re.IGNORECASE)


def test_requires_place_or_bbox():
    import pytest

    with pytest.raises(ValueError, match="place"):
        api.resolve_area()
