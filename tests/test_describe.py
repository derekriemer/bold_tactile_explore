import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytest
from conftest import FIXTURE_BBOX, FIXTURE_CACHE
from shapely.geometry import LineString

from tactile_terrain import api, describe
from tactile_terrain.compose import PlacedLine
from tactile_terrain.config import DescribeSettings, PrinterProfile
from tactile_terrain.describe import DescribeInput, PrintPoint
from tactile_terrain.geo import PrintTransform
from tactile_terrain.pipeline.stages import Heightfield
from tactile_terrain.spec import Spec
from tactile_terrain.styles import resolve_style
from tactile_terrain.tactile.profile import load_profile

BBOX = (-105.80, 39.88, -105.76, 39.91)
BASE = 3.0
G = 1.0
NX, NY = 101, 151  # 100 mm east-west by 150 mm north-south
SNAPSHOT = Path(__file__).parent / "fixtures" / "describe_snapshot.txt"
PROFILE = load_profile("standard")


def line(name, type_, style, coords):
    return PlacedLine(name, type_, resolve_style(style, PROFILE), LineString(coords))


def make_input(terrain=None, lines=(), points=(), types=("river", "road", "lift"), mode="terrain"):
    terrain = np.full((NY, NX), BASE) if terrain is None else terrain
    styles = {"river": "rounded_major", "creek": "rounded_minor", "road": "flat_top", "lift": "pointed"}
    spec = Spec.model_validate(
        {
            "name": "synthetic",
            "mode": mode,
            "area": {"bbox": list(BBOX)},
            "print": {"printer": "louisville-library", "scale_m_per_mm": 100, "base_mm": BASE},
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
            "features": [
                {"type": t, "provider": "osm", "style": styles[t], "filter": {}} for t in types
            ],
        }
    )
    transform = PrintTransform.build(BBOX, scale_m_per_mm=100, base_mm=BASE, min_elevation_m=2000)
    hf = Heightfield(terrain.copy(), G, transform, terrain_z=terrain, lines=list(lines))
    printer = PrinterProfile(bed_mm=[152, 152, 158], nozzle_mm=0.5, grid_mm=G, bed_margin_mm=5)
    return DescribeInput(spec, PROFILE, printer, hf, DescribeSettings(), list(points))


def cone_at(cx, cy, peak, radius=12.0):
    yy, xx = np.mgrid[0:NY, 0:NX] * G
    return peak * np.maximum(0, 1 - np.hypot(xx - cx, yy - cy) / radius)


# --- line courses -------------------------------------------------------------------------


def test_line_course_in_order():
    coords = [(60, 0), (60, 50), (60 - 30 / 2**0.5, 50 + 30 / 2**0.5), (0, 50 + 30 / 2**0.5)]
    text = "\n".join(
        describe.line_features(
            make_input(lines=[line("Test Creek", "river", "rounded_major", coords)])
        )
    )
    order = [
        text.index("Enters the south edge at x = 60 mm"),
        text.index("north for 50 mm"),
        text.index("north-west for 30 mm"),
        text.index("exits the west edge"),
    ]
    assert order == sorted(order)


def test_small_wiggle_is_absorbed():
    coords = [(60, 0), (60, 20), (63, 20), (63, 40)]
    text = "\n".join(
        describe.line_features(make_input(lines=[line("Wiggly", "river", "rounded_major", coords)]))
    )
    assert "north for 43 mm" in text and "east" not in text.replace("south edge", "")


def test_lift_reports_terminals_lower_first():
    terrain = BASE + np.mgrid[0:NY, 0:NX][0] * 0.1  # rises to the north
    lift = line("Test Lift", "lift", "pointed", [(80, 100), (60, 60)])
    text = "\n".join(describe.line_features(make_input(terrain=terrain, lines=[lift])))
    bottom, top = text.index("Bottom terminal at x = 60 mm, y = 60 mm"), text.index("Top terminal")
    assert bottom < top and "x = 80 mm, y = 100 mm" in text[top:]
    assert re.search(r"elevation \d+ m", text) and "heading north-east" in text


def test_longest_line_first():
    short = line("Short One", "river", "rounded_major", [(10, 10), (10, 30)])
    long = line("Long One", "river", "rounded_major", [(20, 10), (20, 90)])
    text = "\n".join(describe.line_features(make_input(lines=[short, long])))
    assert text.index("Long One") < text.index("Short One")


def test_crossing_reported_once_with_taller_on_top():
    river = line("The River", "river", "rounded_major", [(10, 50), (90, 50)])
    road = line("The Road", "road", "flat_top", [(50, 10), (50, 90)])
    text = "\n".join(describe.crossings(make_input(lines=[river, road])))
    assert text.count("crosses") == 1
    assert "x = 50 mm, y = 50 mm" in text and "The Road is on top" in text


# --- summits ------------------------------------------------------------------------------


def test_summits_ordered_higher_first_and_named():
    terrain = BASE + cone_at(30, 40, 8.0) + cone_at(70, 110, 14.0)
    point = PrintPoint("Big Peak", "peak", 71.0, 109.0, 4000.0)
    text = "\n".join(describe.high_low_points(make_input(terrain=terrain, points=[point])))
    higher, lower = text.index("x = 70 mm, y = 110 mm"), text.index("x = 30 mm, y = 40 mm")
    assert higher < lower
    assert "(Big Peak)" in text[higher:lower] and "(Big Peak)" not in text[lower:]
    assert "Lowest point" in text


def test_far_peak_name_is_not_used():
    terrain = BASE + cone_at(70, 110, 14.0)
    point = PrintPoint("Far Peak", "peak", 90.0, 110.0)
    assert "Far Peak" not in "\n".join(
        describe.high_low_points(make_input(terrain=terrain, points=[point]))
    )


# --- cross-sections -----------------------------------------------------------------------


def test_default_sections_every_ten_mm():
    text = "\n".join(describe.cross_sections(make_input()))
    assert text.count("East-west section") == 3 and text.count("North-south section") == 1
    assert "x = 10 mm: 3.0 mm" in text and "x = 90 mm" in text and "y = 140 mm" in text


def test_extra_sections_every_five_mm_and_through_name():
    creek = line("Test Creek", "river", "rounded_major", [(10, 80), (90, 80)])
    m = make_input(lines=[creek])
    text = "\n".join(
        describe.cross_sections(m, [{"y_mm": 40}, {"through": "test creek", "direction": "NS"}])
    )
    assert "East-west section at y = 40 mm, every 5 mm" in text and "x = 15 mm" in text
    assert "North-south section through test creek at x = 50 mm" in text


def test_unknown_through_name_lists_known_names():
    creek = line("Test Creek", "river", "rounded_major", [(10, 80), (90, 80)])
    with pytest.raises(ValueError, match="Test Creek"):
        describe.cross_sections(make_input(lines=[creek]), [{"through": "Nowhere"}])


# --- legend and distortion ----------------------------------------------------------------


def test_legend_lists_exactly_the_styles_in_use():
    text = "\n".join(describe.legend(make_input(types=("river", "lift"))))
    assert "River:" in text and "Lift:" in text and "Road:" not in text
    assert "rounded ridge" in text and "pointed ridge" in text


def test_distortion_states_none_and_the_exaggeration():
    text = "\n".join(describe.distortion(make_input()))
    assert "No horizontal distortion" in text and "1 times everywhere" in text


# --- output rules -------------------------------------------------------------------------

UNIT = r"(?:mm|m|km|times|%)\b"
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?!\w)")
FORBIDDEN = re.compile(r"\b(?:image|images|see|shown|colour|color)\b", re.IGNORECASE)
PATH_LINES = ("Folder:", "STL file:", "Spec file:", "Attribution file:")


def check_output_rules(text):
    for raw in text.splitlines():
        assert len(raw) <= 200, raw
        assert raw.count("|") < 4, raw  # no tables wider than four columns
        assert not FORBIDDEN.search(raw), raw
        if raw.removeprefix("- ").startswith(PATH_LINES):
            continue
        for hit in NUMBER.finditer(raw):
            rest = raw[hit.end() :].lstrip()
            assert re.match(UNIT, rest) or rest.startswith(("%", "percent")), (
                f"number without a unit: {raw!r} at {hit.group(0)}"
            )


def test_synthetic_output_follows_the_rules():
    terrain = BASE + cone_at(30, 40, 8.0)
    lines = [
        line("The River", "river", "rounded_major", [(10, 50), (90, 50)]),
        line("The Road", "road", "flat_top", [(50, 10), (50, 90)]),
        line("A Lift", "lift", "pointed", [(80, 100), (60, 60)]),
    ]
    text = describe.describe(make_input(terrain=terrain, lines=lines))
    check_output_rules(text)
    assert "image" not in text.lower()


# --- the whole thing, from the recorded fixture -------------------------------------------


@pytest.fixture
def fixture_model(models_dir):
    shutil.copytree(FIXTURE_CACHE, models_dir / "wp" / "cache", dirs_exist_ok=True)
    api.create_model(
        "wp",
        area=list(FIXTURE_BBOX),
        print={"scale_m_per_mm": 15, "z_exaggeration": 1.5, "base_mm": 3.0},
        features=[
            {"type": "river", "provider": "nhd", "style": "rounded_major",
             "filter": {"min_stream_order": 4, "include_names": ["Fraser River"]}},
            {"type": "road", "provider": "osm", "style": "flat_top",
             "filter": {"classes": ["primary"], "include_refs": ["US 40"]}},
            {"type": "lift", "provider": "osm", "style": "pointed",
             "filter": {"aerialway": "all", "exclude": ["magic_carpet"]}},
        ],
    )  # fmt: skip
    return models_dir


def test_fixture_description_matches_snapshot(fixture_model):
    text = api.describe_model("wp").replace(str(fixture_model), "<MODELS>").replace("\\", "/")
    check_output_rules(text)
    if os.environ.get("TACTILE_UPDATE_SNAPSHOT"):
        SNAPSHOT.write_text(text, encoding="utf-8")
    assert text == SNAPSHOT.read_text(encoding="utf-8")


def test_describe_model_requires_an_existing_model(models_dir):
    with pytest.raises(FileNotFoundError, match="nope"):
        api.describe_model("nope")


def test_one_named_stream_in_two_styles_is_one_entity():
    lines = [
        line("Parry Creek", "river", "rounded_major", [(10, 50), (50, 50)]),
        line("Parry Creek", "creek", "rounded_minor", [(50, 50), (90, 50)]),
    ]
    text = describe.describe(make_input(lines=lines, types=("river", "creek")))
    assert text.count("### Parry Creek") == 1
    assert "river style rounded_major and creek style rounded_minor" in text
    assert "Piece B, creek style rounded_minor:" in text


def test_output_is_markdown_with_a_title_and_headings():
    text = describe.describe(make_input())
    assert text.startswith("# Tactile model description:")
    assert "\n## Summary\n\n- Model:" in text
