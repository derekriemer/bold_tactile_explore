"""Dashed lines: replace the raised line ridges with a row of small rectangular blocks.

A port of the stand-alone dash-trails 1.0.0 tool (tests/oracle/dash_trails_v1.py), which works on
a finished heightfield. It finds the raised lines from the surface itself, fills the ridges back
into the ground, and places blocks along each line's centreline, turned to follow it. The blocks
are joined to the terrain with a boolean union, so the mesh stays one watertight solid.

The arithmetic is kept as in 1.0.0, so the output matches the tool's output on the same STL
(tests/test_dash_golden.py). Block sizes come from the tactile profile's [dashes] table
(invariant 1). The other numbers below are detection tuning and printability geometry, not
tactile sizes; each is listed in tests/tactile_literal_allowlist.txt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import manifold3d as mf
import numpy as np
import trimesh
from scipy import ndimage, sparse
from scipy.interpolate import RegularGridInterpolator
from scipy.sparse.linalg import spsolve
from skan import Skeleton, summarize
from skimage.morphology import disk, remove_small_objects, skeletonize

from tactile_terrain.tactile.profile import DashSettings

# Printability geometry: how far blocks sink below the lowest ground under them, so they fuse.
EMBED_MM = 0.6
# Detection tuning from dash-trails 1.0.0 (image processing, not tactile sizes).
OPENING_RADIUS_MM = 2.0  # lines narrower than this stand out above a grey opening
CURVATURE_SIGMA = 0.8  # Gaussian Laplacian smoothing, in cells
CREASE_CURVATURE = 0.13  # Laplacian above this is a sharp crease at a ridge's foot
CREASE_MAX_NOISE_CELLS = 10  # creases of up to this many cells are noise
CREASE_REACH_MM = 1.2  # a ridge cell must be this close to a crease
RIDGE_MIN_RISE_MM = 0.2  # a ridge stands at least this far above the opening
CLOSING_RADIUS_MM = 0.6  # close small gaps along a ridge
PINHOLE_MAX_MM2 = 1.5  # holes up to this size are filled; larger loops stay open
NOISE_MAX_MM2 = 8.0  # ridge pieces up to this size are dropped
OUTCROP_MAX_LENGTH_MM = 20.0  # shorter pieces are checked for an uneven height
OUTCROP_MIN_SAMPLES = 3
OUTCROP_SPREAD = 0.55  # standard deviation over mean height above which a piece is an outcrop
MIN_SPUR_MM = 6.0  # side spurs shorter than this are pruned from a centreline
SPUR_PASSES = 4
MIN_PATH_CELLS = 4
FILL_MARGIN_MM = 0.4  # the filled area reaches this far past the detected ridge
SMOOTH_MIN_POINTS = 8  # centrelines with more points than this are smoothed
SMOOTH_SIGMA_MM = 0.6
SEPARATION_PERIOD_FRACTION = 0.8  # blocks closer than this share of a period are crowded
SEPARATION_GAP_FRACTION = 0.5
EDGE_MARGIN_MM = 0.05  # block corners must stay this far inside the map edge
DIRECTION_STEP_MM = 1.0  # direction is taken from points this far either side
DIRECTION_MIN = 1e-6
FOOTPRINT_SAMPLES = 7  # samples per side when finding the lowest ground under a block
FOOTPRINT_HALF = 0.5
EIGHT_NEIGHBOURS = np.ones((3, 3))  # connectivity structure for labelling
XYZ = 3  # coordinates per vertex


@dataclass
class DashBlock:
    centre: np.ndarray  # print mm, (x, y)
    direction: np.ndarray  # unit vector along the line
    bottom_mm: float
    top_mm: float


@dataclass
class DashResult:
    surface: np.ndarray  # heightfield with the ridges filled in
    blocks: list[DashBlock] = field(default_factory=list)
    segments: int = 0  # centreline pieces found


def _cells(mm: float, res: float) -> int:
    return max(1, round(mm / res))


def _drop_small(mask: np.ndarray, cells: int, connectivity: int = 1) -> np.ndarray:
    """Remove pieces of up to `cells` cells, as 1.0.0's `remove_small_objects(mask, n)` does.

    Under scikit-image 0.26 the deprecated positional `min_size` is passed on as `max_size`, so
    1.0.0 drops pieces up to and including n cells; the golden files were made that way.
    (scikit-image 0.25 and older dropped only pieces smaller than n.)
    """
    return remove_small_objects(mask, max_size=cells, connectivity=connectivity)


def detect_lines(heights: np.ndarray, res: float) -> np.ndarray:
    """Boolean mask of the raised line ridges.

    A line is a narrow raised band (it stands out above a grey opening) whose edges are sharp
    creases (strong positive curvature where the ridge meets the ground). Natural ridgelines are
    raised but have smooth flanks, so the crease test rejects them.
    """
    r = _cells(OPENING_RADIUS_MM, res)
    yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
    tophat = heights - ndimage.grey_opening(heights, footprint=(xx**2 + yy**2) <= r * r)
    curvature = ndimage.gaussian_laplace(heights, CURVATURE_SIGMA)
    creases = _drop_small(curvature > CREASE_CURVATURE, CREASE_MAX_NOISE_CELLS, connectivity=2)
    near_crease = ndimage.binary_dilation(creases, disk(_cells(CREASE_REACH_MM, res)))
    band = (tophat > RIDGE_MIN_RISE_MM) & near_crease
    band = ndimage.binary_closing(band, disk(_cells(CLOSING_RADIUS_MM, res)))
    holes = ndimage.binary_fill_holes(band) & ~band  # fill only pinholes, not loops between lines
    band |= _drop_small(holes, int(PINHOLE_MAX_MM2 / res**2)) ^ holes
    band = _drop_small(band, int(NOISE_MAX_MM2 / res**2), connectivity=2)
    # Short pieces whose height above the surroundings is erratic are rock outcrops or cliff
    # edges, not lines: a line ridge has a steady height.
    skeleton = skeletonize(band)
    labels, n = ndimage.label(band, structure=EIGHT_NEIGHBOURS)
    for i in range(1, n + 1):
        on = skeleton & (labels == i)
        rise = tophat[on]
        if on.sum() * res < OUTCROP_MAX_LENGTH_MM and (
            len(rise) < OUTCROP_MIN_SAMPLES or rise.std() > OUTCROP_SPREAD * rise.mean()
        ):
            band[labels == i] = False
    return band


def centrelines(band: np.ndarray, res: float) -> list[np.ndarray]:
    """Centreline paths of the ridge mask, as (row, column) cell coordinates."""
    sk = skeletonize(band)
    for _ in range(SPUR_PASSES):  # prune short side spurs left by skeletonising a wide band
        try:
            skel = Skeleton(sk)
        except ValueError:
            return []
        branches = summarize(skel, separator="_")
        spurs = branches[
            (branches.branch_type == 1) & (branches.branch_distance * res < MIN_SPUR_MM)
        ]
        if len(spurs) == 0:
            break
        for bi in spurs.index:
            c = skel.path_coordinates(bi).astype(int)
            ends = (
                skel.paths.indices[skel.paths.indptr[bi]],
                skel.paths.indices[skel.paths.indptr[bi + 1] - 1],
            )
            if skel.degrees[ends[0]] > 2:
                c = c[1:]
            elif skel.degrees[ends[1]] > 2:
                c = c[:-1]
            sk[c[:, 0], c[:, 1]] = False
        sk = skeletonize(sk)
    if sk.sum() < 2:
        return []
    skel = Skeleton(sk)
    paths = (skel.path_coordinates(i) for i in range(skel.n_paths))
    return [p for p in paths if len(p) >= MIN_PATH_CELLS]


def fill_ridges(heights: np.ndarray, band: np.ndarray, res: float) -> np.ndarray:
    """Replace ridge cells with a smooth surface stitched to the surrounding ground."""
    mask = ndimage.binary_dilation(band, disk(_cells(FILL_MARGIN_MM, res)))
    pts = np.argwhere(mask)
    if len(pts) == 0:
        return heights.copy()
    ny, nx = heights.shape
    idx = -np.ones(heights.shape, int)
    idx[mask] = np.arange(len(pts))
    i, j = pts[:, 0], pts[:, 1]
    rows, cols, vals = [], [], []
    diag = np.zeros(len(pts))
    b = np.zeros(len(pts))
    k = np.arange(len(pts))
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        a, c = i + di, j + dj
        ok = (a >= 0) & (a < ny) & (c >= 0) & (c < nx)  # off-map neighbours are ignored
        diag += ok
        ac, cc = np.clip(a, 0, ny - 1), np.clip(c, 0, nx - 1)
        inside = ok & mask[ac, cc]
        rows.append(k[inside])
        cols.append(idx[ac[inside], cc[inside]])
        vals.append(-np.ones(inside.sum()))
        outside = ok & ~mask[ac, cc]
        np.add.at(b, k[outside], heights[ac[outside], cc[outside]])
    rows.append(k)
    cols.append(k)
    vals.append(diag)
    shape = (len(pts), len(pts))
    matrix = sparse.csr_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=shape
    )
    filled = heights.copy()
    filled[mask] = spsolve(matrix, b)
    return filled


def place_blocks(
    paths: list[np.ndarray], surface: np.ndarray, res: float, dash: DashSettings
) -> list[DashBlock]:
    ny, nx = surface.shape
    xmax, ymax = (nx - 1) * res, (ny - 1) * res
    interp = RegularGridInterpolator(
        (np.arange(ny) * res, np.arange(nx) * res), surface, bounds_error=False, fill_value=None
    )
    length, width, gap = dash.length_mm, dash.width_mm, dash.gap_mm
    period = length + gap
    min_sep = min(period * SEPARATION_PERIOD_FRACTION, length + SEPARATION_GAP_FRACTION * gap)
    centres: list[np.ndarray] = []
    blocks: list[DashBlock] = []
    g = np.linspace(-FOOTPRINT_HALF, FOOTPRINT_HALF, FOOTPRINT_SAMPLES)
    for path in sorted(paths, key=len, reverse=True):  # longest lines first
        xy = path[:, ::-1] * res
        if len(xy) > SMOOTH_MIN_POINTS:
            xy = ndimage.gaussian_filter1d(xy, SMOOTH_SIGMA_MM / res, axis=0, mode="nearest")
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        total = s[-1]
        if total < length:
            continue
        n_blocks = int((total - length) // period) + 1
        start = (total - (n_blocks - 1) * period) / 2  # centre the pattern on the segment

        def at(d, s=s, xy=xy):
            return np.array([np.interp(d, s, xy[:, 0]), np.interp(d, s, xy[:, 1])])

        for k in range(n_blocks):
            sc = start + k * period
            p = at(sc)
            t = at(sc + DIRECTION_STEP_MM) - at(sc - DIRECTION_STEP_MM)
            if np.linalg.norm(t) < DIRECTION_MIN:
                continue
            t /= np.linalg.norm(t)
            n = np.array([-t[1], t[0]])
            corners = np.array(
                [
                    p + sa * t * length / 2 + sb * n * width / 2
                    for sa in (-1, 1)
                    for sb in (-1, 1)
                ]
            )
            if (
                (corners < EDGE_MARGIN_MM).any()
                or (corners[:, 0] > xmax - EDGE_MARGIN_MM).any()
                or (corners[:, 1] > ymax - EDGE_MARGIN_MM).any()
            ):
                continue
            if centres and np.min(np.linalg.norm(np.array(centres) - p, axis=1)) < min_sep:
                continue
            samples = np.array([p + u * t * length + w * n * width for u in g for w in g])
            z = interp(samples[:, ::-1])
            zc = interp(p[::-1][None])[0]
            centres.append(p)
            blocks.append(DashBlock(p, t, float(z.min() - EMBED_MM), float(zc + dash.height_mm)))
    return blocks


def apply(z: np.ndarray, res: float, dash: DashSettings) -> DashResult:
    """Find the raised lines in `z`, fill them in, and place the blocks.

    `z` is rounded to float32 first: dash-trails 1.0.0 read its heights back from a float32 STL,
    and its thresholds must see the same numbers.
    """
    heights = np.asarray(z, dtype=np.float32).astype(float)
    band = detect_lines(heights, res)
    paths = centrelines(band, res)
    surface = fill_ridges(heights, band, res)
    return DashResult(surface, place_blocks(paths, surface, res, dash), len(paths))


def heightfield_solid(surface: np.ndarray, res: float, zbase: float) -> trimesh.Trimesh:
    """Closed solid of the heightfield, triangulated as dash-trails 1.0.0 does (the boolean
    union's output depends on the input triangulation)."""
    ny, nx = surface.shape
    xs, ys = np.meshgrid(np.arange(nx) * res, np.arange(ny) * res)
    top = np.c_[xs.ravel(), ys.ravel(), surface.ravel()]
    vid = np.arange(nx * ny).reshape(ny, nx)
    a, b = vid[:-1, :-1].ravel(), vid[:-1, 1:].ravel()
    c, d = vid[1:, 1:].ravel(), vid[1:, :-1].ravel()
    faces = [np.c_[a, b, c], np.c_[a, c, d]]
    loop = np.r_[vid[0, :], vid[1:, -1], vid[-1, -2::-1], vid[-2:0:-1, 0]]
    nb = len(loop)
    bottom = top[loop].copy()
    bottom[:, 2] = zbase
    vertices = np.vstack([top, bottom, [[xs.max() / 2, ys.max() / 2, zbase]]])
    bi = nx * ny + np.arange(nb)
    centre = len(vertices) - 1
    nxt = np.roll(np.arange(nb), -1)
    faces += [
        np.c_[loop, bi, bi[nxt]],
        np.c_[loop, bi[nxt], loop[nxt]],
        np.c_[np.full(nb, centre), bi[nxt], bi],
    ]
    mesh = trimesh.Trimesh(vertices, np.vstack(faces), process=False)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def build_mesh(
    result: DashResult,
    res: float,
    dash: DashSettings,
    zbase: float = 0,
    terrain: trimesh.Trimesh | None = None,
):
    """The filled terrain plus every block, as one watertight mesh.

    `terrain` is the solid to add the blocks to; by default the full-resolution filled surface.
    """
    if terrain is None:
        terrain = heightfield_solid(result.surface, res, zbase)
    solid = mf.Manifold(
        mf.Mesh(
            vert_properties=np.asarray(terrain.vertices, np.float32),
            tri_verts=np.asarray(terrain.faces, np.uint32),
        )
    )
    boxes = []
    for block in result.blocks:
        d, p = block.direction, block.centre
        box = mf.Manifold.cube(
            [dash.length_mm, dash.width_mm, block.top_mm - block.bottom_mm], center=True
        )
        box = box.rotate([0, 0, float(np.degrees(np.arctan2(d[1], d[0])))]).translate(
            [p[0], p[1], (block.bottom_mm + block.top_mm) / 2]
        )
        boxes.append(box)
    if boxes:
        solid = solid + mf.Manifold.batch_boolean(boxes, mf.OpType.Add)
    out = solid.to_mesh()
    mesh = trimesh.Trimesh(out.vert_properties[:, :XYZ], out.tri_verts, process=True)
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:  # drop zero-volume slivers from float rounding
        mesh = max(parts, key=lambda part: len(part.faces))
    return mesh


__all__ = ["DashBlock", "DashResult", "apply", "build_mesh", "heightfield_solid"]
