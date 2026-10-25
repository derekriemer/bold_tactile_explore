"""Binary STL exporter."""

from __future__ import annotations

from pathlib import Path

import trimesh

from tactile_terrain.registry import exporters


def export_stl(mesh: trimesh.Trimesh, path: str | Path) -> Path:
    """Binary STL file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(trimesh.exchange.stl.export_stl(mesh))
    return path


exporters.register("stl", export_stl)
