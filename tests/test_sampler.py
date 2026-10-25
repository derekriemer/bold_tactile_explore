import numpy as np
import pytest
import trimesh
from helpers import assert_printable

from tactile_terrain import api
from tactile_terrain.config import load_config
from tactile_terrain.sampler import build_plate
from tactile_terrain.spec import Spec


def make_spec(profile="standard", seed=1, focus=None, overrides=None, printer="louisville-library"):
    return Spec.model_validate(
        {
            "name": f"sampler-{profile}",
            "mode": "flat",
            "area": {"bbox": [0, 0, 0.001, 0.001]},
            "print": {"printer": printer, "scale_m_per_mm": 1, "base_mm": 3.0},
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
            "style": {"tactile_profile": profile, "overrides": overrides or {}},
            "kind": "sampler",
            "sampler": {"focus": focus, "seed": seed},
        }
    )


def plate(**kw):
    return build_plate(
        make_spec(**kw), load_config().printer(kw.get("printer", "louisville-library"))
    )


def shapes(cell):
    return tuple(line.shape for line in cell.lines)


def test_plate_is_printable_and_fits():
    from tactile_terrain.mesh import heightfield_to_mesh

    p = plate()
    assert_printable(heightfield_to_mesh(p.z, p.grid_mm))
    assert p.width_mm <= 140 and p.height_mm <= 120
    assert p.width_mm <= 142 and p.height_mm <= 142  # the library bed minus its margin


def test_plate_never_exceeds_a_small_bed():
    cfg = load_config()
    small = cfg.printers["louisville-library"].model_copy(update={"bed_mm": [120, 120, 100]})
    p = build_plate(make_spec(), small)
    assert p.width_mm <= 110 and p.height_mm <= 110
    assert p.sample_length_mm < p.requested_length_mm


def test_row_one_has_every_pair_including_both_controls():
    row = plate().rows[0]
    pairs = [frozenset(shapes(c)) for c in row.cells if not c.control]
    controls = [shapes(c) for c in row.cells if c.control]
    assert sorted(map(sorted, pairs)) == [
        ["flat_top", "pointed"],
        ["flat_top", "rounded"],
        ["pointed", "rounded"],
    ]
    assert sorted(controls) == [("flat_top", "flat_top"), ("rounded", "rounded")]
    assert all(len(set(shapes(c))) == 1 for c in row.cells if c.control)


def test_same_seed_same_layout_different_seed_different_order():
    def order(seed):
        return [shapes(c) for c in plate(seed=seed).rows[0].cells]

    assert order(5) == order(5)
    assert len({tuple(order(s)) for s in range(1, 8)}) > 1
    first, second = plate(seed=5), plate(seed=5)
    assert np.array_equal(first.z, second.z)


def test_rows_widths_heights_and_spacing_follow_the_profile():
    p = plate()
    s = p.profile.sampler
    rows = {r.kind: r for r in p.rows}
    assert [c.lines[0].width_mm for c in rows["widths"].cells] == s.widths_mm
    assert [c.lines[0].height_mm for c in rows["heights"].cells] == s.heights_mm
    assert [c.gap_mm for c in rows["spacing"].cells] == s.spacings_mm
    assert all(c.gap_mm == s.pair_gap_mm for c in rows["profiles"].cells)


def test_numerals_are_raised_where_the_readout_says(models_dir):
    api.create_sampler(seed=3)
    text = api.describe_model("sampler-standard")
    p = plate(seed=3)
    for cell in p.cells:
        assert f"Row {cell.row}, sample {cell.number}:" in text
        assert f"Numeral {cell.number} at x = {cell.centre_x_mm:.0f} mm" in text
        x, y = cell.label_strokes[0][0]
        x2, y2 = cell.label_strokes[0][-1]
        mx, my = (x + x2) / 2, (y + y2) / 2  # the middle of the first stroke
        i, j = round(mx / p.grid_mm), round(my / p.grid_mm)
        near = p.z[j - 1 : j + 2, i - 1 : i + 2].max()
        assert near > p.base_mm + p.profile.label_relief_mm / 2
    assert text.count("Numeral ") == len(p.cells)


def lowered_runs(column, base):
    flags = column < base - 1e-9
    return int(flags[0]) + int(np.count_nonzero(flags[1:] & ~flags[:-1]))


def test_notches_count_the_row_on_the_left_edge_and_mark_north():
    p = plate()
    g = p.grid_mm
    for row in p.rows:
        j0, j1 = round((row.top_mm - row.height_mm) / g), round(row.top_mm / g)
        assert lowered_runs(p.z[j0 : j1 + 1, 0], p.base_mm) == row.number
    x0, _y0, x1, y1 = p.north_notch
    assert p.z[round(y1 / g) - 1, round((x0 + x1) / 2 / g)] < p.base_mm
    assert p.z[round(y1 / g) - 1, 0] == p.base_mm  # only one notch on the north edge
    # The gutters between rows are smooth.
    gutter = p.z[
        round((p.rows[1].top_mm + 0.5) / g) : round(
            (p.rows[0].top_mm - p.rows[0].height_mm - 0.5) / g
        ),
        6:,
    ]
    assert (gutter == p.base_mm).all()


def test_numerals_only_and_braille_is_refused_clearly():
    p = plate()
    assert p.profile.label_mode == "numerals" and all(c.label_strokes for c in p.cells)
    with pytest.raises(ValueError, match="Braille"):
        plate(overrides={"label_mode": "numerals+braille"})


def test_coarse_preset_has_wider_lines_and_fewer_pairs():
    standard = plate(printer="generic-220")
    coarse = plate(profile="coarse", printer="generic-220")
    assert len(coarse.rows[0].cells) < len(standard.rows[0].cells)
    assert all("pointed" not in shapes(c) for c in coarse.rows[0].cells)
    assert len([c for c in coarse.rows[0].cells if c.control]) == 2
    assert coarse.rows[1].cells[0].lines[0].width_mm > standard.rows[1].cells[0].lines[0].width_mm
    assert coarse.profile.label_height_mm > standard.profile.label_height_mm


def test_focus_makes_a_plate_with_one_row():
    p = plate(focus="spacing")
    assert [r.kind for r in p.rows] == ["spacing"] and p.rows[0].number == 1
    with pytest.raises(ValueError, match="widths"):
        plate(focus="bananas")


def test_create_check_list_and_refuse_editing(models_dir):
    summary = api.create_sampler(profile="standard", seed=2, name="plate")
    assert "Built sampler plate plate" in summary
    assert_printable(trimesh.load(models_dir / "plate" / "plate.stl"))
    spec_text = (models_dir / "plate" / "spec.json").read_text(encoding="utf-8")
    assert '"kind": "sampler"' in spec_text and '"seed": 2' in spec_text
    assert "Row 1, sample 1:" in (models_dir / "plate" / "DESCRIPTION.md").read_text(
        encoding="utf-8"
    )
    assert "plate: sampler plate" in api.list_models()
    assert "watertight yes" in api.check_print("plate")
    assert (models_dir / "plate" / "print-pack" / "PRINT-NOTES.txt").exists()
    with pytest.raises(ValueError, match="create_sampler"):
        api.update_model("plate", {"z_multiply": 2})
    with pytest.raises(ValueError, match="create_sampler"):
        api.analyze_model("plate")
    with pytest.raises(FileExistsError):
        api.create_sampler(name="plate")
    assert api.create_sampler(name="plate", overwrite=True)


def test_ordinary_specs_do_not_gain_sampler_keys():
    text = Spec.model_validate(
        {
            "name": "x",
            "area": {"bbox": [0, 0, 1, 1]},
            "print": {"printer": "louisville-library", "scale_m_per_mm": 10},
            "elevation": {"provider": "usgs3dep", "resolution_m": 10},
        }
    ).model_dump_json()
    assert "kind" not in text and "sampler" not in text
