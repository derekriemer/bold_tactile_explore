"""Tactile profiles: numbers and choices only (invariants 1 and 6)."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from tactile_terrain.config import profiles_dir

PRESET_NAMES = ["fine", "standard", "coarse", "extra_coarse"]


class LineStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["rounded", "flat_top", "pointed"]
    width_mm: float
    height_mm: float

    @model_validator(mode="after")
    def _pointed_is_tall_enough(self) -> LineStyle:
        if self.profile == "pointed" and self.height_mm < self.width_mm / 2:
            raise ValueError(
                f"pointed line height {self.height_mm} mm must be at least half its width "
                f"({self.width_mm} mm)"
            )
        return self


class SamplerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_length_mm: float
    pair_gap_mm: float
    widths_mm: list[float]
    heights_mm: list[float]
    spacings_mm: list[float]
    plate_width_mm: float = 140.0  # target plate size, clamped to the printer bed
    plate_height_mm: float = 120.0
    margin_mm: float = 4.0
    gutter_mm: float = 8.0  # smooth space between rows
    cell_gap_mm: float = 6.0  # between neighbouring samples in a row
    length_shrink: float = 0.8  # samples shrink by this factor until the plate fits
    min_sample_length_mm: float = 10.0


class TactileProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    min_line_width_mm: float
    min_line_height_mm: float
    min_parallel_spacing_mm: float
    min_feature_length_mm: float
    min_relief_mm: float
    target_relief_mm: float
    simplify_mm: float
    distinguishable_profiles: list[Literal["rounded", "flat_top", "pointed"]]
    label_mode: Literal["numerals", "numerals+braille", "numerals+jumbo_braille"]
    label_height_mm: float
    label_stroke_mm: float
    label_relief_mm: float
    notch_width_mm: float
    notch_depth_mm: float
    lines: dict[str, LineStyle]
    sampler: SamplerSettings


def _raw(name: str) -> dict:
    """Raw TOML for a user profile (preferred) or a shipped preset."""
    user = profiles_dir() / f"{name}.toml"
    if user.exists():
        return tomllib.loads(user.read_text(encoding="utf-8"))
    preset = files("tactile_terrain.tactile") / "presets" / f"{name}.toml"
    if preset.is_file():
        return tomllib.loads(preset.read_text(encoding="utf-8"))
    raise KeyError(f"Unknown tactile profile '{name}'. Valid names: {', '.join(profile_names())}")


def profile_names() -> list[str]:
    user_dir = profiles_dir()
    user = [p.stem for p in user_dir.glob("*.toml")] if user_dir.is_dir() else []
    return sorted(set(PRESET_NAMES) | set(user))


def _merge(parent: dict, child: dict) -> dict:
    merged = dict(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve(name: str, seen: tuple[str, ...]) -> dict:
    if name in seen:
        raise ValueError(f"Tactile profile 'extends' cycle: {' -> '.join((*seen, name))}")
    raw = _raw(name)
    parent = raw.pop("extends", "")
    if not parent:
        return raw
    return _merge(_resolve(parent, (*seen, name)), raw)


def load_profile(name: str) -> TactileProfile:
    data = _resolve(name, ())
    data["name"] = name
    return TactileProfile.model_validate(data)


def apply_overrides(profile: TactileProfile, overrides: dict) -> TactileProfile:
    """Return the profile with the spec's explicit `style.overrides` merged in and re-validated."""
    if not overrides:
        return profile
    return TactileProfile.model_validate(_merge(profile.model_dump(), overrides))
