"""Heightfield to closed triangle mesh, with no booleans."""

from __future__ import annotations

import numpy as np
import trimesh


def heightfield_to_mesh(z: np.ndarray, grid_mm: float) -> trimesh.Trimesh:
    """Top surface, four walls down to z = 0, and a flat bottom.

    `z` has shape (ny, nx); row 0 is y = 0 (south), column 0 is x = 0 (west). Vertices sit on
    grid points, so the mesh extent is (nx - 1) * grid_mm by (ny - 1) * grid_mm.
    """
    z = np.asarray(z, dtype=float)
    ny, nx = z.shape
    if ny < 2 or nx < 2:
        raise ValueError("heightfield needs at least 2 x 2 points")

    jj, ii = np.mgrid[0:ny, 0:nx]
    top = np.column_stack([ii.ravel() * grid_mm, jj.ravel() * grid_mm, z.ravel()])
    idx = np.arange(ny * nx).reshape(ny, nx)

    # Top: two upward-facing triangles per cell.
    v00, v10, v11, v01 = idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]
    top_faces = np.concatenate(
        [
            np.stack([v00, v10, v11], -1).reshape(-1, 3),
            np.stack([v00, v11, v01], -1).reshape(-1, 3),
        ]
    )

    # Perimeter of the top grid, counter-clockwise seen from above.
    ring = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, :0:-1], idx[:0:-1, 0]])
    n = len(ring)
    bottom_ring = np.column_stack([top[ring, :2], np.zeros(n)])
    centre = np.array([[(nx - 1) * grid_mm / 2, (ny - 1) * grid_mm / 2, 0.0]])
    base = ny * nx
    bot = base + np.arange(n)
    bot_next = base + (np.arange(n) + 1) % n
    ring_next = np.roll(ring, -1)
    centre_idx = np.full(n, base + n)

    # Outward-facing walls, two triangles per perimeter edge.
    walls = np.concatenate(
        [
            np.stack([ring, bot, bot_next], -1),
            np.stack([ring, bot_next, ring_next], -1),
        ]
    )
    # Bottom: a fan from the centre, facing down.
    bottom_faces = np.stack([centre_idx, bot_next, bot], -1)

    vertices = np.concatenate([top, bottom_ring, centre])
    faces = np.concatenate([top_faces, walls, bottom_faces])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
