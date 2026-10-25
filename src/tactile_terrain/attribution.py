"""ATTRIBUTION.txt: credit every data source a model used."""

from __future__ import annotations

from pathlib import Path

from tactile_terrain import __version__, providers  # noqa: F401  (registers the providers)
from tactile_terrain.providers.base import SourceInfo
from tactile_terrain.registry import elevation_providers, line_providers
from tactile_terrain.spec import Spec


def sources_used(spec: Spec) -> list[SourceInfo]:
    found: dict[str, SourceInfo] = {}
    if spec.mode == "terrain":
        info = elevation_providers.get(spec.elevation.provider).source
        found[info.name] = info
    for feature in spec.features:
        info = line_providers.get(feature.provider).source
        found[info.name] = info
    return list(found.values())


def attribution_text(spec: Spec) -> str:
    lines = [f"Attribution for the tactile model '{spec.name}'", ""]
    for info in sources_used(spec):
        lines += [f"{info.name}", f"  Licence: {info.licence}", f"  {info.attribution}", ""]
    lines.append(f"Generated with tactile-terrain {__version__}.")
    return "\n".join(lines) + "\n"


def write_attribution(spec: Spec, path: Path) -> Path:
    path.write_text(attribution_text(spec), encoding="utf-8")
    return path
