"""Geometry fingerprints for golden-file tests.

A golden STL is 64 MB, too large for git, so only its fingerprint is committed: the face count,
volume, area, bounds, and a raster of the highest vertex in each 0.5 mm cell. Comparing a mesh to
a fingerprint gives a plain-text report, so a failure reads without looking at a render.

Cells are offset by 0.05 mm so that no grid vertex (multiples of the 0.2 or 0.25 mm print grid)
sits on a cell edge, where float32 noise could move it into the next cell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

CELL_MM = 0.5
CELL_OFFSET_MM = 0.05
HEIGHT_TOLERANCE_MM = 1e-3
VOLUME_TOLERANCE = 1e-6  # relative
WORST_REPORTED = 5


def raster(mesh: trimesh.Trimesh, shape: tuple[int, int] | None = None) -> np.ndarray:
    v = np.asarray(mesh.vertices)
    ix = np.floor((v[:, 0] + CELL_OFFSET_MM) / CELL_MM).astype(int)
    iy = np.floor((v[:, 1] + CELL_OFFSET_MM) / CELL_MM).astype(int)
    if shape is None:
        shape = (int(iy.max()) + 1, int(ix.max()) + 1)
    keep = (ix >= 0) & (iy >= 0) & (ix < shape[1]) & (iy < shape[0])
    grid = np.zeros(shape, dtype=np.float32)
    np.maximum.at(grid, (iy[keep], ix[keep]), v[keep, 2].astype(np.float32))
    return grid


def fingerprint(mesh: trimesh.Trimesh) -> dict:
    return {
        "faces": len(mesh.faces),
        "watertight": bool(mesh.is_watertight),
        "volume_mm3": float(mesh.volume),
        "area_mm2": float(mesh.area),
        "bounds_mm": np.asarray(mesh.bounds, dtype=float).round(4).tolist(),
    }


def save(mesh: trimesh.Trimesh, path: str | Path, source: str = "") -> Path:
    """Write <path>.json (summary) and <path>.npz (height raster)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = fingerprint(mesh) | {"source": source}
    path.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    np.savez_compressed(path.with_suffix(".npz"), raster=raster(mesh))
    return path


@dataclass
class Report:
    ok: bool
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines)


def _compass(x: float, y: float, width: float, height: float) -> str:
    ns = "south" if y < height / 3 else "north" if y > 2 * height / 3 else ""
    ew = "west" if x < width / 3 else "east" if x > 2 * width / 3 else ""
    return f"{ns}-{ew}".strip("-") or "middle"


def compare(mesh: trimesh.Trimesh, path: str | Path, label: str = "") -> Report:
    """Compare a mesh with a saved fingerprint."""
    path = Path(path)
    want = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    want_raster = np.load(path.with_suffix(".npz"))["raster"]
    got = fingerprint(mesh)
    got_raster = raster(mesh, want_raster.shape)
    lines = [f"Golden comparison: {label or path.stem}"]
    ok = True

    def check(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok &= passed
        lines.append(f"- {name}: {'pass' if passed else 'FAIL'}. {detail}")

    check("face count", got["faces"] == want["faces"], f"{got['faces']} (golden {want['faces']})")
    check("watertight", got["watertight"], f"{got['watertight']}")
    rel = abs(got["volume_mm3"] - want["volume_mm3"]) / want["volume_mm3"]
    check(
        "volume",
        rel <= VOLUME_TOLERANCE,
        f"{got['volume_mm3']:.1f} mm³ (golden {want['volume_mm3']:.1f}, relative difference "
        f"{rel:.2e})",
    )
    same_bounds = np.allclose(got["bounds_mm"], want["bounds_mm"], atol=HEIGHT_TOLERANCE_MM)
    check("bounds", same_bounds, f"{got['bounds_mm']} (golden {want['bounds_mm']})")
    diff = np.abs(got_raster.astype(float) - want_raster.astype(float))
    bad = diff > HEIGHT_TOLERANCE_MM
    check(
        "height raster",
        not bad.any(),
        f"{int(bad.sum())} of {bad.size} cells differ by more than {HEIGHT_TOLERANCE_MM} mm; "
        f"largest difference {diff.max():.4f} mm",
    )
    if bad.any():
        h, w = (s * CELL_MM for s in want_raster.shape)
        for flat in np.argsort(diff, axis=None)[::-1][:WORST_REPORTED]:
            iy, ix = np.unravel_index(flat, diff.shape)
            x, y = (ix + 0.5) * CELL_MM, (iy + 0.5) * CELL_MM
            lines.append(
                f"  - at x {x:.1f} mm, y {y:.1f} mm ({_compass(x, y, w, h)}): "
                f"{got_raster[iy, ix]:.3f} mm, golden {want_raster[iy, ix]:.3f} mm"
            )
    return Report(ok, lines)


def assert_matches(mesh: trimesh.Trimesh, path: str | Path, label: str = "") -> Report:
    report = compare(mesh, path, label)
    assert report.ok, "\n" + report.text()
    return report
