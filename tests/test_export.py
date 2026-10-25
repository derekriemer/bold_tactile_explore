import numpy as np
import trimesh
from helpers import assert_printable

from tactile_terrain.mesh import heightfield_to_mesh
from tactile_terrain.registry import exporters


def test_stl_reloads_printable(tmp_path):
    import tactile_terrain.export.stl  # noqa: F401

    z = 2 + np.random.default_rng(1).random((12, 15))
    path = exporters.get("stl")(heightfield_to_mesh(z, 0.25), tmp_path / "out.stl")
    reloaded = trimesh.load(path)
    assert_printable(reloaded)
    assert reloaded.bounds[1][2] == np.float32(z.max())
