"""Remake the golden fingerprints from the STLs listed in README.md."""

import sys
from pathlib import Path

import trimesh

HERE = Path(__file__).parent
ROOT = HERE.parents[3]  # topo_tactile_maps
sys.path.insert(0, str(HERE.parents[1]))
import golden

SOURCES = {
    "tilden_off": "drive-download-20261106T205231Z-1-001/tilden_berkeley_sample/print-pack/tilden_berkeley_sample.stl",
    "tilden_dashed_2mm": "additions/golden/tilden_dashed_2mm_v1.stl",
    "tilden_dashed_1mm": "additions/golden/tilden_dashed_1mm_v1.stl",
}

for name, rel in SOURCES.items():
    mesh = trimesh.load(ROOT / rel, force="mesh")
    golden.save(mesh, HERE / name, source=rel)
    print(name, golden.fingerprint(mesh))
