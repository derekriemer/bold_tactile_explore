"""Heightfield to closed triangle mesh, with no booleans."""

from __future__ import annotations

import itertools

import numpy as np
import trimesh

BLOCK_CELLS = 16  # decimation works on blocks of this many cells per side
# Larger blocks are tried when small ones cannot reach the size limit.
BLOCK_SIZES = (16, 32, 64, 128, 256, 512, 1024)
STL_HEADER_BYTES = 84
STL_BYTES_PER_FACE = 50
BYTES_PER_MB = 1_000_000
# Flatness tolerances to try, as fractions of the grid cell, until the size limit is met.
TOLERANCE_STEPS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0)


def _spans(n_vertices: int, block: int) -> list[tuple[int, int]]:
    edges = [*range(0, n_vertices - 1, block), n_vertices - 1]
    return list(itertools.pairwise(edges))


def _flat_blocks(z: np.ndarray, tolerance: float, block: int) -> list[tuple]:
    """Blocks that a single plane fits within `tolerance`: (j0, j1, i0, i1, plane coefficients)."""
    ny, nx = z.shape
    found = []
    for j0, j1 in _spans(ny, block):
        for i0, i1 in _spans(nx, block):
            bh, bw = j1 - j0, i1 - i0
            if bw * bh <= bw + bh:  # too small for a fan to save any triangles
                continue
            sub = z[j0 : j1 + 1, i0 : i1 + 1]
            jj, ii = np.mgrid[0 : bh + 1, 0 : bw + 1]
            design = np.column_stack([ii.ravel(), jj.ravel(), np.ones(ii.size)])
            coef, *_ = np.linalg.lstsq(design, sub.ravel(), rcond=None)
            if np.abs(design @ coef - sub.ravel()).max() <= tolerance:
                found.append((j0, j1, i0, i1, coef))
    return found


def heightfield_to_mesh(
    z: np.ndarray,
    grid_mm: float,
    flat_tolerance_mm: float | None = None,
    block: int = BLOCK_CELLS,
) -> trimesh.Trimesh:
    """Top surface, four walls down to z = 0, and a flat bottom.

    `z` has shape (ny, nx); row 0 is y = 0 (south), column 0 is x = 0 (west). Vertices sit on
    grid points, so the mesh extent is (nx - 1) * grid_mm by (ny - 1) * grid_mm.

    With `flat_tolerance_mm`, blocks that one plane fits within that tolerance are replaced by a
    fan from the block centre to the block's border vertices. Border vertices are kept, so
    neighbouring blocks still share every edge and the mesh stays watertight.
    """
    z = np.asarray(z, dtype=float)
    ny, nx = z.shape
    if ny < 2 or nx < 2:
        raise ValueError("heightfield needs at least 2 x 2 points")

    jj, ii = np.mgrid[0:ny, 0:nx]
    top = np.column_stack([ii.ravel() * grid_mm, jj.ravel() * grid_mm, z.ravel()])
    idx = np.arange(ny * nx).reshape(ny, nx)

    flat = [] if flat_tolerance_mm is None else _flat_blocks(z, flat_tolerance_mm, block)
    keep = np.ones((ny - 1, nx - 1), dtype=bool)
    for j0, j1, i0, i1, _ in flat:
        keep[j0:j1, i0:i1] = False

    # Top: two upward-facing triangles per full-resolution cell.
    v00, v10, v11, v01 = (a[keep] for a in (idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]))
    parts = [np.stack([v00, v10, v11], -1), np.stack([v00, v11, v01], -1)]

    # Flat blocks: a fan from an extra centre vertex to the border, counter-clockwise.
    extra = []
    next_vertex = ny * nx
    for j0, j1, i0, i1, coef in flat:
        centre_i, centre_j = (i0 + i1) / 2, (j0 + j1) / 2
        plane_z = coef[0] * (centre_i - i0) + coef[1] * (centre_j - j0) + coef[2]
        extra.append([centre_i * grid_mm, centre_j * grid_mm, plane_z])
        border = np.concatenate(
            [idx[j0, i0:i1], idx[j0:j1, i1], idx[j1, i1:i0:-1], idx[j1:j0:-1, i0]]
        )
        parts.append(np.stack([np.full(border.size, next_vertex), border, np.roll(border, -1)], -1))
        next_vertex += 1
    top_faces = np.concatenate(parts)
    if extra:
        top = np.concatenate([top, np.array(extra)])

    # Perimeter of the top grid, counter-clockwise seen from above.
    ring = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, :0:-1], idx[:0:-1, 0]])
    n = len(ring)
    bottom_ring = np.column_stack([top[ring, :2], np.zeros(n)])
    centre = np.array([[(nx - 1) * grid_mm / 2, (ny - 1) * grid_mm / 2, 0.0]])
    base = len(top)
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
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if flat:
        mesh.remove_unreferenced_vertices()
    return mesh


def stl_size_mb(mesh: trimesh.Trimesh) -> float:
    return (STL_HEADER_BYTES + STL_BYTES_PER_FACE * len(mesh.faces)) / BYTES_PER_MB


def mesh_within_size(
    z: np.ndarray, grid_mm: float, max_stl_mb: float
) -> tuple[trimesh.Trimesh, float | None]:
    """The full mesh, or the least decimated mesh under the size limit (0 means no limit).

    Returns the mesh and the flatness tolerance used (None when nothing was decimated).
    """
    mesh = heightfield_to_mesh(z, grid_mm)
    if not max_stl_mb or stl_size_mb(mesh) <= max_stl_mb:
        return mesh, None
    best = (mesh, None)
    for step in TOLERANCE_STEPS:
        tolerance = grid_mm * step
        for block in BLOCK_SIZES:
            mesh = heightfield_to_mesh(z, grid_mm, flat_tolerance_mm=tolerance, block=block)
            if stl_size_mb(mesh) <= max_stl_mb:
                return mesh, tolerance
            if stl_size_mb(mesh) < stl_size_mb(best[0]):
                best = (mesh, tolerance)
    return best
