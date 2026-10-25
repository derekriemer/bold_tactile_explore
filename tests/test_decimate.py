import numpy as np
import pytest
from helpers import assert_printable
from shapely.geometry import MultiLineString

from tactile_terrain.compose import PlacedLine, raise_lines
from tactile_terrain.mesh import heightfield_to_mesh, mesh_within_size, stl_size_mb
from tactile_terrain.styles import resolve_style
from tactile_terrain.tactile.profile import load_profile

G = 0.25
N = 241  # 60 mm square
BASE = 3.0


def ridged_plate():
    style = resolve_style("flat_top", load_profile("standard"))
    lines = [
        PlacedLine("a", "road", style, MultiLineString([[(0, 20), (60, 20)]])),
        PlacedLine("b", "road", style, MultiLineString([[(40, 0), (40, 60)]])),
    ]
    return raise_lines(np.full((N, N), BASE), G, lines), style


def test_flat_plate_with_ridges_decimates_under_the_limit_and_stays_printable():
    z, style = ridged_plate()
    full = heightfield_to_mesh(z, G)
    limit = stl_size_mb(full) * 0.4
    mesh, tolerance = mesh_within_size(z, G, limit)
    assert_printable(mesh)
    assert tolerance is not None and stl_size_mb(mesh) <= limit
    # Ridge heights survive within one grid cell, and nothing else grew.
    assert mesh.bounds[1][2] == pytest.approx(z.max(), abs=G)
    ridge_column = mesh.vertices[np.isclose(mesh.vertices[:, 0], 30.0)]
    assert ridge_column[:, 2].max() == pytest.approx(BASE + style.height_mm, abs=G)
    assert mesh.volume == pytest.approx(full.volume, rel=0.01)


def test_no_limit_or_a_loose_limit_leaves_the_mesh_alone():
    z, _ = ridged_plate()
    full = heightfield_to_mesh(z, G)
    for limit in (0, stl_size_mb(full) * 2):
        mesh, tolerance = mesh_within_size(z, G, limit)
        assert tolerance is None and len(mesh.faces) == len(full.faces)


def test_sloping_terrain_is_not_flattened_beyond_tolerance():
    yy, xx = np.mgrid[0:N, 0:N] * G
    z = BASE + 0.5 * np.sin(xx / 4) + 0.5 * np.cos(yy / 5)
    mesh = heightfield_to_mesh(z, G, flat_tolerance_mm=G / 20)
    assert_printable(mesh)
    assert len(mesh.faces) >= len(heightfield_to_mesh(z, G).faces) * 0.9


def test_planar_slope_collapses_to_fans_and_stays_exact():
    yy, xx = np.mgrid[0:N, 0:N] * G
    z = BASE + 0.02 * xx + 0.01 * yy
    full = heightfield_to_mesh(z, G)
    mesh = heightfield_to_mesh(z, G, flat_tolerance_mm=G / 20)
    assert_printable(mesh)
    assert len(mesh.faces) < len(full.faces) / 4
    assert mesh.volume == pytest.approx(full.volume, rel=1e-6)
