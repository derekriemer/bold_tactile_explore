"""doctor: an environment report in plain text."""

from __future__ import annotations

import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from tactile_terrain import __version__
from tactile_terrain.config import UserConfig, config_path
from tactile_terrain.printpack import find_slicer
from tactile_terrain.providers.http import USER_AGENT
from tactile_terrain.tactile.profile import profile_names

CHECK_TIMEOUT_S = 10.0

ENDPOINTS = {
    "USGS 3DEP elevation service": (
        "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer?f=json"
    ),
    "USGS NHDPlus HR service": (
        "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer?f=json"
    ),
    "Nominatim place search": "https://nominatim.openstreetmap.org/status",
}


def _reachable(url: str) -> str:
    import httpx

    try:
        response = httpx.get(
            url, timeout=CHECK_TIMEOUT_S, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
    except httpx.HTTPError as error:
        return f"unreachable ({type(error).__name__}: {error})"
    ok = response.status_code < 400
    return "reachable" if ok else f"answered with error status {response.status_code}"


def _writable(folder) -> str:
    target = folder
    while not target.exists() and target.parent != target:
        target = target.parent
    return "writable" if os.access(target, os.W_OK) else f"NOT writable (checked {target})"


def run_doctor(cfg: UserConfig) -> str:
    try:
        package = version("tactile-terrain")
    except PackageNotFoundError:
        package = __version__
    overpass = cfg.overpass_endpoint
    endpoints = {
        **ENDPOINTS,
        "Overpass (OpenStreetMap data)": overpass.removesuffix("interpreter") + "status",
    }
    slicer = find_slicer()
    lines = [
        "Doctor report",
        f"tactile-terrain {package}, Python {platform.python_version()} on {platform.system()}.",
        f"Executable: {sys.executable}",
        f"Config file: {config_path()}",
        f"Models folder: {cfg.models_path} ({_writable(cfg.models_path)}).",
        f"Tactile profile active: {cfg.active_profile}. Available: {', '.join(profile_names())}.",
        f"Printers: {', '.join(cfg.printers)}. Default: {cfg.default_printer}.",
        "Data services:",
        *[f"  {name}: {_reachable(url)}" for name, url in endpoints.items()],
        f"Slicer: {slicer or 'none found (PrusaSlicer or OrcaSlicer on PATH enables print time)'}.",
    ]
    return "\n".join(lines)
