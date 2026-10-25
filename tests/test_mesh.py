import numpy as np
import pytest
from helpers import assert_printable
from synthetic import cone, valley

from tactile_terrain.mesh import heightfield_to_mesh

GRID = 0.5


def _field(grid):
    return grid.data[::-1]  # synthetic rows run north to south; mesh rows run south to north


@pytest.mark.parametrize(
    "z",
    [
        np.full((21, 21), 3.0),
        _field(cone(n=41)) / 100,
        _field(valley(n=41)) / 100,
        np.random.default_rng(0).random((17, 9)) * 5 + 1,
    ],
    ids=["flat", "cone", "valley", "noise"],
)
def test_mesh_is_printable_with_exact_bounds(z):
    mesh = heightfield_to_mesh(z, GRID)
    assert_printable(mesh)
    ny, nx = z.shape
    lo, hi = mesh.bounds
    assert np.allclose(lo, [0, 0, 0], atol=1e-6)
    assert np.allclose(hi, [(nx - 1) * GRID, (ny - 1) * GRID, z.max()], atol=1e-6)


def test_flat_block_volume():
    mesh = heightfield_to_mesh(np.full((11, 11), 3.0), 1.0)
    assert_printable(mesh)
    assert mesh.volume == pytest.approx(300.0, abs=1e-6)


def test_rejects_degenerate_grid():
    with pytest.raises(ValueError):
        heightfield_to_mesh(np.ones((1, 5)), 1.0)
