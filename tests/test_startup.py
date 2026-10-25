import subprocess
import sys

HEAVY = ["rasterio", "py3dep", "pynhd", "trimesh", "scipy", "shapely", "numpy"]


def test_importing_the_server_does_not_import_heavy_libraries():
    code = (
        "import sys; import tactile_terrain.server; "
        f"print([m for m in {HEAVY!r} if m in sys.modules])"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"
