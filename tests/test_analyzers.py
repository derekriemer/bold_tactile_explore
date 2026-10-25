import math

import numpy as np
import pytest
from shapely.geometry import LineString
from synthetic import cone

from tactile_terrain.analyzers import AnalysisContext, format_analysis, run_all
from tactile_terrain.analyzers.bed_fit import BedFit
from tactile_terrain.analyzers.min_width import MinWidth
from tactile_terrain.analyzers.relief import Relief
from tactile_terrain.analyzers.resolution import Resolution
from tactile_terrain.analyzers.spacing import Spacing
from tactile_terrain.compose import PlacedLine
from tactile_terrain.config import PrinterProfile
from tactile_terrain.geo import PrintTransform
from tactile_terrain.pipeline.stages import Heightfield
from tactile_terrain.spec import Spec
from tactile_terrain.styles import resolve_style
from tactile_terrain.tactile.profile import apply_overrides, load_profile

BBOX = (-105.80, 39.88, -105.76, 39.91)
BASE = 3.0


def printer(**kw):
    args = {"bed_mm": [152, 152, 158], "nozzle_mm": 0.5, "grid_mm": 0.25, "bed_margin_mm": 5}
    return PrinterProfile(**(args | kw))


def make_ctx(
    z=None,
    terrain_z=None,
    grid=0.25,
    scale=100,
    exaggeration=1.0,
    lines=(),
    mode="terrain",
    features=(),
    overrides=None,
    prn=None,
    source_res=10.0,
):
    z = np.full((41, 41), BASE) if z is None else z
    spec = Spec.model_validate(
        {
            "name": "t",
            "mode": mode,
            "area": {"bbox": list(BBOX)},
            "print": {
                "printer": "louisville-library",
                "scale_m_per_mm": scale,
                "z_exaggeration": exaggeration,
                "base_mm": BASE,
            },
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
            "features": [
                {"type": "x", "provider": "osm", "style": s, "filter": {}} for s in features
            ],
            "style": {"tactile_profile": "standard", "overrides": overrides or {}},
        }
    )
    transform = PrintTransform.build(
        BBOX, scale_m_per_mm=scale, z_exaggeration=exaggeration, base_mm=BASE
    )
    hf = Heightfield(z, grid, transform, terrain_z=terrain_z, lines=list(lines))
    profile = apply_overrides(load_profile("standard"), overrides or {})
    return AnalysisContext(spec, profile, prn or printer(), hf, source_res)


def cone_relief(peak_mm):
    """A cone grid whose printed relief above the base peaks at peak_mm."""
    data = cone(peak_m=peak_mm, base_m=0.0, radius_m=300, n=61, res=10).data
    return BASE + data


# --- relief -------------------------------------------------------------------------------


def test_relief_suggests_exaggeration_for_target_relief():
    terrain = cone_relief(2.0)
    ctx = make_ctx(z=terrain, terrain_z=terrain)
    result = Relief().analyze(ctx)
    spread = float(np.percentile(terrain - BASE, 98) - np.percentile(terrain - BASE, 2))
    target = ctx.profile.target_relief_mm
    expected = round(target / spread * 2) / 2
    (s,) = result.suggestions
    assert s.severity == "warn"
    assert s.patch == {"print": {"z_exaggeration": expected}}
    assert result.metrics["relief_spread_mm"] == pytest.approx(spread)


def test_relief_suggestion_is_capped_by_printer_height():
    terrain = cone_relief(2.0)
    prn = printer(bed_mm=[152, 152, 10])
    result = Relief().analyze(make_ctx(z=terrain, terrain_z=terrain, prn=prn))
    (s,) = result.suggestions
    cap = math.floor((10 - BASE) / 2.0 * 2) / 2
    assert s.patch == {"print": {"z_exaggeration": cap}}
    assert "limited by the printer height" in s.message


def test_relief_flags_a_model_too_tall_for_the_bed():
    terrain = cone_relief(30.0)
    prn = printer(bed_mm=[152, 152, 20])
    (s,) = Relief().analyze(make_ctx(z=terrain, terrain_z=terrain, prn=prn)).suggestions
    assert s.severity == "error" and s.patch["print"]["z_exaggeration"] < 1.0


def test_relief_is_quiet_when_relief_is_enough():
    terrain = cone_relief(20.0)
    assert Relief().analyze(make_ctx(z=terrain, terrain_z=terrain)).suggestions == []


def test_relief_skipped_in_flat_mode():
    result = Relief().analyze(make_ctx(mode="flat"))
    assert result.metrics == {} and result.suggestions == []


# --- minimum width ------------------------------------------------------------------------


def test_min_width_warns_and_patches_to_three_nozzles():
    overrides = {"lines": {"rounded_major": {"width_mm": 1.0}}}
    ctx = make_ctx(features=["rounded_major"], overrides=overrides)
    (s,) = MinWidth().analyze(ctx).suggestions
    assert s.severity == "warn"
    assert s.patch == {"style": {"overrides": {"lines": {"rounded_major": {"width_mm": 1.5}}}}}


def test_min_width_keeps_pointed_flanks_steep():
    overrides = {"lines": {"pointed": {"width_mm": 1.0, "height_mm": 0.6}}}
    ctx = make_ctx(features=["pointed"], overrides=overrides, prn=printer(nozzle_mm=1.0))
    (s,) = MinWidth().analyze(ctx).suggestions
    changes = s.patch["style"]["overrides"]["lines"]["pointed"]
    assert changes["width_mm"] == 3.0 and changes["height_mm"] >= changes["width_mm"] / 2


def test_min_width_quiet_for_adequate_styles():
    ctx = make_ctx(features=["flat_top"], prn=printer(nozzle_mm=0.4))
    assert MinWidth().analyze(ctx).suggestions == []


# --- bed fit ------------------------------------------------------------------------------


def test_bed_fit_errors_and_suggests_smallest_multiple_of_five():
    z = np.full((190, 129), BASE)  # 128 mm east-west by 189 mm north-south at a 1 mm grid
    ctx = make_ctx(z=z, grid=1.0, scale=100)
    (s,) = BedFit().analyze(ctx).suggestions
    usable = 152 - 2 * 5
    expected = 5 * math.ceil(100 * 189 / usable / 5)
    assert s.severity == "error"
    assert s.patch == {"print": {"scale_m_per_mm": float(expected)}}
    assert expected == 135


def test_bed_fit_accepts_a_model_that_fits():
    assert BedFit().analyze(make_ctx(z=np.full((101, 101), BASE), grid=1.0)).suggestions == []


# --- parallel spacing ---------------------------------------------------------------------


def _pair(offset):
    style = resolve_style("rounded_major", load_profile("standard"))
    a = PlacedLine("Alpha", "river", style, LineString([(0, 20), (20, 20)]))
    b = PlacedLine("Beta", "road", style, LineString([(0, 20 + offset), (20, 20 + offset)]))
    return [a, b]


def test_close_parallel_lines_are_reported_with_position():
    width = resolve_style("rounded_major", load_profile("standard")).width_mm
    result = Spacing().analyze(make_ctx(lines=_pair(width + 2.0)))
    (s,) = result.suggestions
    assert "Alpha" in s.message and "Beta" in s.message
    assert "2.0 mm apart" in s.message and "20.0 mm" in s.message
    assert "x = 10 mm" in s.message


def test_well_separated_lines_are_not_reported():
    width = resolve_style("rounded_major", load_profile("standard")).width_mm
    assert Spacing().analyze(make_ctx(lines=_pair(width + 4.0))).suggestions == []


# --- resolution ---------------------------------------------------------------------------


def test_fine_source_on_coarse_grid_reports_detail_lost():
    ctx = make_ctx(grid=0.2, scale=100, source_res=1.0)
    (s,) = Resolution().analyze(ctx).suggestions
    assert s.severity == "info" and "averaged away" in s.message and "20 m" in s.message


def test_coarse_source_reports_interpolation():
    ctx = make_ctx(grid=0.2, scale=10, source_res=30.0)
    (s,) = Resolution().analyze(ctx).suggestions
    assert "interpolated" in s.message


def test_resolution_skipped_in_flat_mode():
    assert Resolution().analyze(make_ctx(source_res=None)).suggestions == []


# --- formatting ---------------------------------------------------------------------------


def test_warnings_come_first_and_carry_a_fix():
    terrain = cone_relief(2.0)
    ctx = make_ctx(z=terrain, terrain_z=terrain, source_res=1.0)
    text = format_analysis(run_all(ctx))
    lines = text.splitlines()
    assert lines[0].startswith("WARN: ") and lines[1].startswith("  Fix: set print.z_exaggeration")
    assert text.index("WARN") < text.index("INFO")


def test_a_floor_made_of_three_nozzles_is_not_flagged_for_float_error():
    overrides = {"lines": {"rounded_major": {"width_mm": 1.2}}}
    ctx = make_ctx(features=["rounded_major"], overrides=overrides, prn=printer(nozzle_mm=0.4))
    assert MinWidth().analyze(ctx).suggestions == []  # 3 x 0.4 is 1.2000000000000002 in floats
    ctx = make_ctx(
        features=["rounded_major"],
        overrides={"lines": {"rounded_major": {"width_mm": 1.0}}},
        prn=printer(nozzle_mm=0.4),
    )
    assert MinWidth().analyze(ctx).suggestions[0].patch["style"]["overrides"]["lines"][
        "rounded_major"
    ] == {"width_mm": 1.2}


def test_joined_pieces_of_one_feature_are_not_close_parallels():
    style = resolve_style("flat_top", load_profile("standard"))
    a = PlacedLine("Main Street", "road", style, LineString([(0, 20), (30, 20)]))
    b = PlacedLine("", "road", style, LineString([(30, 20), (60, 20)]))
    assert Spacing().analyze(make_ctx(lines=[a, b])).suggestions == []


def test_one_named_stream_in_two_styles_is_not_its_own_close_parallel():
    profile = load_profile("standard")
    a = PlacedLine(
        "Vasquez Creek",
        "river",
        resolve_style("rounded_major", profile),
        LineString([(0, 20), (30, 20)]),
    )
    b = PlacedLine(
        "Vasquez Creek",
        "creek",
        resolve_style("rounded_minor", profile),
        LineString([(30, 20), (60, 20)]),
    )
    assert Spacing().analyze(make_ctx(lines=[a, b])).suggestions == []
