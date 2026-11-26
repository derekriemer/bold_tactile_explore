#!/usr/bin/env python3
"""
dash_trails.py — turn the raised trail ridges on a terrain-map STL into a
3D dashed line of rectangular blocks.

The input must be a heightfield-style STL: one solid with a flat bottom and a
top surface sampled on a regular XY grid (the format these trail maps use).

Usage
    dash-trails input.stl [output.stl] [options]
    (or: python3 dash_trails.py input.stl ...)

Common options
    --height 1.0     block height above the ground, mm          (default 1.0)
    --width 2.0      block width across the trail, mm           (default 2.0)
    --length 2.0     block length along the trail, mm           (default 2.0)
    --gap 2.0        space between blocks along the trail, mm   (default 2.0)
    --preview        also save a top-down PNG next to the output showing the
                     smoothed terrain and where every block went

Install: see README.md (pip install .)
"""
import argparse, sys, warnings

__version__ = "1.0.0"
from pathlib import Path
import numpy as np

warnings.filterwarnings("ignore")
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve
from scipy.interpolate import RegularGridInterpolator
from skimage.morphology import skeletonize, disk, remove_small_objects
from skan import Skeleton, summarize
import trimesh
import manifold3d as mf


# ---------------------------------------------------------------- loading
def load_heightmap(path):
    m = trimesh.load(path, force="mesh")
    v = m.vertices
    zmin = m.bounds[0, 2]
    top = v[v[:, 2] > zmin + 1e-6]
    x0, y0 = m.bounds[0, 0], m.bounds[0, 1]
    xs = np.unique(np.round(top[:, 0] - x0, 4))
    res = float(np.median(np.diff(xs)))
    ix = np.round((top[:, 0] - x0) / res).astype(int)
    iy = np.round((top[:, 1] - y0) / res).astype(int)
    H = np.full((iy.max() + 1, ix.max() + 1), np.nan)
    H[iy, ix] = top[:, 2]
    if np.isnan(H).any():  # fill any holes with nearest neighbour
        idx = ndimage.distance_transform_edt(np.isnan(H), return_distances=False, return_indices=True)
        H = H[tuple(idx)]
    return H, res, (x0, y0, zmin)


# ---------------------------------------------------------------- detection
def detect_trails(H, res):
    """Boolean mask of the raised trail ridges.

    A trail is a narrow raised band (stands out above a morphological opening)
    whose edges are sharp creases (strong positive curvature right where the
    ridge meets the ground). Natural ridgelines are raised but have smooth
    flanks, so the crease test rejects them.
    """
    px = lambda mm: max(1, int(round(mm / res)))
    r = px(2.0)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    tophat = H - ndimage.grey_opening(H, footprint=(xx**2 + yy**2) <= r * r)
    L = ndimage.gaussian_laplace(H, 0.8)               # per-pixel curvature
    creases = remove_small_objects(L > 0.13, 10, connectivity=2)
    near_crease = ndimage.binary_dilation(creases, disk(px(1.2)))
    band = (tophat > 0.2) & near_crease
    band = ndimage.binary_closing(band, disk(px(0.6)))
    holes = ndimage.binary_fill_holes(band) & ~band          # fill only pinholes, not
    band |= remove_small_objects(holes, int(1.5 / res**2)) ^ holes  # loops between trails
    band = remove_small_objects(band, int(8.0 / res**2), connectivity=2)  # < 8 mm² = noise
    # Short pieces whose height above the surroundings is erratic are rock
    # outcrops / cliff edges, not trails (a trail ridge has a steady height).
    sk = skeletonize(band)
    lab, n = ndimage.label(band, structure=np.ones((3, 3)))
    for i in range(1, n + 1):
        on = sk & (lab == i)
        v = tophat[on]
        if on.sum() * res < 20 and (len(v) < 3 or v.std() > 0.55 * v.mean()):
            band[lab == i] = False
    return band


def centerlines(band, res, min_spur_mm=6.0):
    sk = skeletonize(band)
    for _ in range(4):  # prune short side-spurs left by skeletonising a wide band
        try:
            S = Skeleton(sk)
        except ValueError:
            return []
        sd = summarize(S, separator="_")
        spurs = sd[(sd.branch_type == 1) & (sd.branch_distance * res < min_spur_mm)]
        if len(spurs) == 0:
            break
        for bi in spurs.index:
            c = S.path_coordinates(bi).astype(int)
            ends = S.paths.indices[S.paths.indptr[bi]], S.paths.indices[S.paths.indptr[bi + 1] - 1]
            if S.degrees[ends[0]] > 2: c = c[1:]
            elif S.degrees[ends[1]] > 2: c = c[:-1]
            sk[c[:, 0], c[:, 1]] = False
        sk = skeletonize(sk)
    if sk.sum() < 2:
        return []
    S = Skeleton(sk)
    return [S.path_coordinates(i) for i in range(S.n_paths) if len(S.path_coordinates(i)) >= 4]


# ---------------------------------------------------------------- terrain fix
def remove_ridges(H, band, res):
    """Replace ridge cells with a smooth surface stitched to the surrounding ground."""
    mask = ndimage.binary_dilation(band, disk(max(1, int(round(0.4 / res)))))
    pts = np.argwhere(mask)
    if len(pts) == 0:
        return H.copy()
    ny, nx = H.shape
    idx = -np.ones(H.shape, int); idx[mask] = np.arange(len(pts))
    i, j = pts[:, 0], pts[:, 1]
    rows, cols, vals = [], [], []
    diag = np.zeros(len(pts)); b = np.zeros(len(pts)); k = np.arange(len(pts))
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        a, c = i + di, j + dj
        ok = (a >= 0) & (a < ny) & (c >= 0) & (c < nx)      # off-map neighbours are ignored
        diag += ok
        ac, cc = np.clip(a, 0, ny - 1), np.clip(c, 0, nx - 1)
        inside = ok & mask[ac, cc]
        rows.append(k[inside]); cols.append(idx[ac[inside], cc[inside]]); vals.append(-np.ones(inside.sum()))
        outside = ok & ~mask[ac, cc]
        np.add.at(b, k[outside], H[ac[outside], cc[outside]])
    rows.append(k); cols.append(k); vals.append(diag)
    A = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(len(pts),) * 2)
    Hc = H.copy(); Hc[mask] = spsolve(A, b)
    return Hc


# ---------------------------------------------------------------- blocks
def place_blocks(paths, Hc, res, a):
    ny, nx = Hc.shape
    xmax, ymax = (nx - 1) * res, (ny - 1) * res
    interp = RegularGridInterpolator((np.arange(ny) * res, np.arange(nx) * res), Hc,
                                     bounds_error=False, fill_value=None)
    period = a.length + a.gap
    min_sep = min(period * 0.8, a.length + 0.5 * a.gap)
    centers, blocks = [], []
    g = np.linspace(-0.5, 0.5, 7)
    for pth in sorted(paths, key=len, reverse=True):      # longest trails first
        xy = pth[:, ::-1] * res
        if len(xy) > 8:
            xy = ndimage.gaussian_filter1d(xy, 0.6 / res, axis=0, mode="nearest")
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        L = s[-1]
        if L < a.length:
            continue
        n_blk = int((L - a.length) // period) + 1
        start = (L - (n_blk - 1) * period) / 2              # centre the pattern on the segment
        at = lambda d: np.array([np.interp(d, s, xy[:, 0]), np.interp(d, s, xy[:, 1])])
        for k in range(n_blk):
            sc = start + k * period
            p = at(sc); t = at(sc + 1) - at(sc - 1)
            if np.linalg.norm(t) < 1e-6:
                continue
            t /= np.linalg.norm(t); n = np.array([-t[1], t[0]])
            corners = np.array([p + sa * t * a.length / 2 + sb * n * a.width / 2 for sa in (-1, 1) for sb in (-1, 1)])
            if (corners < 0.05).any() or (corners[:, 0] > xmax - 0.05).any() or (corners[:, 1] > ymax - 0.05).any():
                continue
            if centers and np.min(np.linalg.norm(np.array(centers) - p, axis=1)) < min_sep:
                continue
            samp = np.array([p + u * t * a.length + w * n * a.width for u in g for w in g])
            z = interp(samp[:, ::-1])
            zc = interp(p[::-1][None])[0]
            centers.append(p)
            blocks.append((p, t, z.min() - a.embed, zc + a.height))
    return blocks


# ---------------------------------------------------------------- meshing
def heightfield_solid(Hc, res, zbase):
    ny, nx = Hc.shape
    X, Y = np.meshgrid(np.arange(nx) * res, np.arange(ny) * res)
    top = np.c_[X.ravel(), Y.ravel(), Hc.ravel()]
    vid = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = vid[:-1, :-1].ravel(), vid[:-1, 1:].ravel(), vid[1:, 1:].ravel(), vid[1:, :-1].ravel()
    F = [np.c_[a, b, c], np.c_[a, c, d]]
    loop = np.r_[vid[0, :], vid[1:, -1], vid[-1, -2::-1], vid[-2:0:-1, 0]]
    nb = len(loop)
    bot = top[loop].copy(); bot[:, 2] = zbase
    V = np.vstack([top, bot, [[X.max() / 2, Y.max() / 2, zbase]]])
    bi = nx * ny + np.arange(nb); ctr = len(V) - 1; nxt = np.roll(np.arange(nb), -1)
    F += [np.c_[loop, bi, bi[nxt]], np.c_[loop, bi[nxt], loop[nxt]], np.c_[np.full(nb, ctr), bi[nxt], bi]]
    m = trimesh.Trimesh(V, np.vstack(F), process=False)
    if m.volume < 0:
        m.invert()
    return m


def build_mesh(Hc, res, zbase, blocks, a):
    t = heightfield_solid(Hc, res, zbase)
    solid = mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32),
                                tri_verts=np.asarray(t.faces, np.uint32)))
    boxes = []
    for p, d, z0, z1 in blocks:
        bx = mf.Manifold.cube([a.length, a.width, z1 - z0], center=True)
        bx = bx.rotate([0, 0, float(np.degrees(np.arctan2(d[1], d[0])))]).translate([p[0], p[1], (z0 + z1) / 2])
        boxes.append(bx)
    if boxes:
        solid = solid + mf.Manifold.batch_boolean(boxes, mf.OpType.Add)
    mo = solid.to_mesh()
    out = trimesh.Trimesh(mo.vert_properties[:, :3], mo.tri_verts, process=True)
    parts = out.split(only_watertight=False)
    if len(parts) > 1:  # drop zero-volume slivers from float rounding
        out = max(parts, key=lambda p: len(p.faces))
    return out


def save_preview(path, H, Hc, blocks, res):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from matplotlib.patches import Polygon
    ls = LightSource(315, 40)
    ext = [0, (H.shape[1] - 1) * res, 0, (H.shape[0] - 1) * res]
    asp = H.shape[0] / H.shape[1]
    fig, ax = plt.subplots(1, 2, figsize=(16, 8 * asp + 0.6))
    for axi, img, title in ((ax[0], H, "original"), (ax[1], Hc, f"ridges removed + {len(blocks)} blocks")):
        axi.imshow(ls.shade(img, plt.cm.gray, vert_exag=3, dx=res, dy=res), origin="lower", extent=ext)
        axi.set_title(title)
    for p, t, *_ in blocks:
        n = np.array([-t[1], t[0]])
        ax[1].add_patch(Polygon([p - t - n, p + t - n, p + t + n, p - t + n], color="red"))
    fig.savefig(path, dpi=80, bbox_inches="tight")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Replace raised trail ridges with a dashed line of blocks.")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--height", type=float, default=1.0)
    ap.add_argument("--width", type=float, default=2.0)
    ap.add_argument("--length", type=float, default=2.0)
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--embed", type=float, default=0.6, help="how far blocks sink below the lowest ground under them, mm")
    ap.add_argument("--preview", action="store_true", help="also save a top-down PNG of the result")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = ap.parse_args()
    inp = Path(a.input)
    out = Path(a.output) if a.output else inp.with_name(f"{inp.stem}_dashed.stl")

    print(f"Reading {inp.name} …")
    H, res, (x0, y0, zbase) = load_heightmap(inp)
    print(f"  grid {H.shape[1]}×{H.shape[0]} at {res:g} mm")
    band = detect_trails(H, res)
    paths = centerlines(band, res)
    print(f"  found {len(paths)} trail segments")
    Hc = remove_ridges(H, band, res)
    blocks = place_blocks(paths, Hc, res, a)
    print(f"  placing {len(blocks)} blocks")
    mesh = build_mesh(Hc, res, zbase, blocks, a)
    mesh.apply_translation([x0, y0, 0])
    mesh.export(out)
    print(f"Wrote {out}  (watertight: {mesh.is_watertight})")
    if a.preview:
        pv = out.with_suffix(".png")
        save_preview(pv, H, Hc, blocks, res)
        print(f"Preview {pv}")


if __name__ == "__main__":
    main()
