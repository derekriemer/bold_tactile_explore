import numpy as np
import pytest
from helpers import assert_printable

from tactile_terrain import printpack
from tactile_terrain.config import PrinterProfile
from tactile_terrain.mesh import heightfield_to_mesh

PRINTER = PrinterProfile(
    bed_mm=[152, 152, 158],
    nozzle_mm=0.5,
    grid_mm=1.0,
    max_print_hours=8,
    filament_density_g_cm3=1.24,
)


def block_report():
    mesh = heightfield_to_mesh(np.full((11, 11), 3.0), 1.0)  # 10 x 10 x 3 mm
    assert_printable(mesh)
    return printpack.mesh_report(mesh, PRINTER)


def text(report, slicer=None, result=None, note=""):
    return printpack.check_text(
        "block", report, PRINTER, slicer, result, note, [], 0.0, "STL size 0.1 MB."
    )


def test_block_volume_and_solid_mass_are_exact_upper_bounds():
    report = block_report()
    assert report.volume_cm3 == pytest.approx(0.300, abs=1e-9)
    assert report.mass_g == pytest.approx(0.372, abs=1e-9)
    output = text(report)
    assert "0.300 cubic centimetres" in output and "0.372 g" in output and "upper bound" in output
    assert "watertight yes" in output and "no supports" in output


def test_without_a_slicer_print_time_is_unavailable_and_the_limit_is_stated(monkeypatch):
    monkeypatch.setattr(printpack.shutil, "which", lambda name: None)
    assert printpack.find_slicer() is None
    output = text(block_report(), slicer=printpack.find_slicer())
    assert "Print time: unavailable" in output and "limit is 8 hours" in output


def test_a_printer_without_a_limit_says_so():
    printer = PrinterProfile(bed_mm=[200, 200, 200], nozzle_mm=0.4, grid_mm=0.2)
    line = printpack.print_time_text(printer, None, None)
    assert "no time limit" in line


def test_slicer_estimates_are_compared_with_the_limit():
    gcode = "; estimated printing time (normal mode) = 9h 30m 0s\n; filament used [g] = 42.5\n"
    result = printpack.parse_gcode_stats(gcode)
    assert result.hours == pytest.approx(9.5) and result.grams == 42.5
    line = printpack.print_time_text(PRINTER, "/bin/slicer", result)
    assert (
        "9.5 hours" in line and "OVER the printer's limit of 8 hours" in line and "42.5 g" in line
    )
    quick = printpack.parse_gcode_stats("; estimated printing time (normal mode) = 1d 2h 3m 4s")
    assert quick.hours == pytest.approx(26 + 3 / 60 + 4 / 3600)


def test_slicer_found_without_config_explains_why():
    line = printpack.print_time_text(PRINTER, "/bin/slicer", None, "No slicer_config.")
    assert "unavailable" in line and "No slicer_config." in line
