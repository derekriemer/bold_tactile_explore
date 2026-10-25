"""Spec schema v1: the typed, validated description of a model."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_serializer, model_validator

from tactile_terrain import config
from tactile_terrain.tactile import profile as tactile_profile

SCHEMA_VERSION = 1
# Maps an old schema_version to a function that upgrades a raw spec dict by one version.
MIGRATIONS: dict[int, Any] = {}

# int | float keeps 125 as 125 and 3.0 as 3.0 so a save reproduces the file byte for byte.
Number = int | float


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Area(_Strict):
    bbox: list[Number]
    crs: str = "auto"

    @model_validator(mode="after")
    def _four_numbers(self) -> Area:
        if len(self.bbox) != 4:
            raise ValueError("bbox must be [west, south, east, north]")
        return self


class Print(_Strict):
    printer: str
    scale_m_per_mm: Number | None = None
    long_side_mm: Number | None = None
    z_exaggeration: Number = 1.0
    base_mm: Number = 3.0

    @model_validator(mode="after")
    def _exactly_one_scale(self) -> Print:
        if (self.scale_m_per_mm is None) == (self.long_side_mm is None):
            raise ValueError("print needs exactly one of scale_m_per_mm or long_side_mm")
        return self

    @model_serializer(mode="wrap")
    def _drop_unused_scale(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for key in ("scale_m_per_mm", "long_side_mm"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class Elevation(_Strict):
    provider: str
    resolution_m: Number


class Feature(_Strict):
    type: str
    provider: str
    style: str
    filter: dict[str, Any] = {}


class Style(_Strict):
    tactile_profile: str = "standard"
    overrides: dict[str, Any] = {}


class SamplerInfo(_Strict):
    """How a sampler plate was laid out, so it can be rebuilt and read out exactly."""

    focus: str | None = None  # one of profiles, widths, heights, spacing; None means all rows
    seed: int
    sample_length_mm: float | None = None  # the length actually used, after any shrinking


class Spec(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    name: str
    mode: Literal["terrain", "flat"] = "terrain"
    area: Area
    print: Print
    elevation: Elevation
    features: list[Feature] = []
    style: Style = Style()
    legend: dict[str, Any] = {}
    regions: list[Any] = []  # reserved, Phase 2
    textures: list[Any] = []  # reserved, Phase 2
    tiles: Any = None  # reserved, Phase 2
    built_with: str = "0.1.0"
    kind: Literal["model", "sampler"] = "model"  # omitted from the file for ordinary models
    sampler: SamplerInfo | None = None  # present only when kind is sampler

    @model_validator(mode="after")
    def _sampler_matches_kind(self) -> Spec:
        if (self.kind == "sampler") != (self.sampler is not None):
            raise ValueError("kind sampler and the sampler section go together")
        return self

    @model_serializer(mode="wrap")
    def _omit_default_kind(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("kind") == "model":
            data.pop("kind", None)
        if data.get("sampler") is None:
            data.pop("sampler", None)
        return data

    @field_validator("name")
    @classmethod
    def _safe_folder_name(cls, name: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError(
                "name may use only letters, digits, '-' and '_', and must start with a letter or digit"
            )
        return name


def validate_registry_names(spec: Spec, cfg: config.UserConfig | None = None) -> None:
    """Check every registry-name field; errors list the valid names."""
    from tactile_terrain import providers  # noqa: F401  (registers the built-in providers)
    from tactile_terrain.registry import elevation_providers, line_providers

    cfg = cfg or config.load_config()
    valid_profiles = tactile_profile.profile_names()
    if spec.style.tactile_profile not in valid_profiles:
        raise ValueError(
            f"Unknown tactile profile '{spec.style.tactile_profile}'. "
            f"Valid names: {', '.join(valid_profiles)}"
        )
    cfg.printer(spec.print.printer)
    if spec.mode == "terrain":
        elevation_providers.get(spec.elevation.provider)
    lines = tactile_profile.apply_overrides(
        tactile_profile.load_profile(spec.style.tactile_profile), spec.style.overrides
    ).lines
    for feature in spec.features:
        line_providers.get(feature.provider)
        if feature.style not in lines:
            raise ValueError(
                f"Unknown line style '{feature.style}' for feature '{feature.type}'. "
                f"Valid names: {', '.join(sorted(lines))}"
            )


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version", SCHEMA_VERSION)
    while version < SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version = data["schema_version"]
    return data


def load_spec(path: str | Path) -> Spec:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Spec.model_validate(_migrate(data))


def save_spec(spec: Spec, path: str | Path) -> None:
    """Write with stable key order (field order) and 2-space indent."""
    text = json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False)
    Path(path).write_text(text + "\n", encoding="utf-8")
