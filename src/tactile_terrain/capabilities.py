"""list_capabilities: every registry, its names and one-line descriptions, as plain text."""

from __future__ import annotations

import inspect
from typing import Any

from tactile_terrain import providers  # noqa: F401  (registers the built-in providers)
from tactile_terrain.config import UserConfig
from tactile_terrain.registry import ALL_REGISTRIES, Registry
from tactile_terrain.tactile.profile import PRESET_NAMES, load_profile, profile_names

HEADINGS = {
    "elevation_providers": "Elevation providers (spec elevation.provider)",
    "line_providers": "Line providers (spec features[].provider)",
    "area_providers": "Area providers",
    "line_styles": "Line cross-section shapes (a tactile profile line style uses one of these)",
    "textures": "Textures",
    "warps": "Horizontal warps",
    "analyzers": "Analyzers (run by create_model, update_model and analyze_model)",
    "joints": "Joints",
    "exporters": "Exporters",
}


def _first_line(obj: Any) -> str:
    source = getattr(obj, "source", None)
    if source is not None:
        return source.name
    doc = inspect.getdoc(obj) if inspect.isroutine(obj) else inspect.getdoc(type(obj))
    return doc.splitlines()[0] if doc else "no description"


def _entry(name: str, obj: Any) -> list[str]:
    lines = [f"  {name}: {_first_line(obj)}"]
    filters = getattr(obj, "filters", None)
    if filters:
        lines += [f"    {kind} filters: {text}" for kind, text in filters.items()]
    params = getattr(obj, "parameters", None)
    if params:
        lines.append(f"    parameters: {params}")
    return lines


def _registry_section(registry: Registry) -> list[str]:
    lines = [HEADINGS.get(registry.kind, registry.kind)]
    names = registry.names()
    if not names:
        return [*lines, "  none yet"]
    for name in names:
        lines += _entry(name, registry.get(name))
    return lines


def list_capabilities(cfg: UserConfig) -> str:
    blocks = [["Capabilities"]]
    blocks += [_registry_section(r) for r in ALL_REGISTRIES]

    active = load_profile(cfg.active_profile)
    profile_lines = [
        "Tactile profiles",
        f"  Presets: {', '.join(PRESET_NAMES)}.",
        f"  Available: {', '.join(profile_names())}.",
        f"  Active: {cfg.active_profile}. Line styles it defines:",
    ]
    for name, entry in active.lines.items():
        profile_lines.append(
            f"    {name}: {entry.profile}, {entry.width_mm:g} mm wide, {entry.height_mm:g} mm tall"
        )
    blocks.append(profile_lines)

    printer_lines = ["Printers", f"  Default: {cfg.default_printer}."]
    for name, p in cfg.printers.items():
        bed = " by ".join(f"{v:g} mm" for v in p.bed_mm)
        limit = f"{p.max_print_hours:g} hours" if p.max_print_hours else "no time limit"
        printer_lines.append(
            f"  {name}: bed {bed}, nozzle {p.nozzle_mm:g} mm, grid {p.grid_mm:g} mm, {limit}"
        )
    blocks.append(printer_lines)
    blocks.append(
        ["Spec modes", "  terrain: elevation plus features.", "  flat: features on a flat plate."]
    )
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"
