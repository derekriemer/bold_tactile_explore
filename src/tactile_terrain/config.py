"""User config (config.toml): units, models_dir, active profile, printers."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import user_config_dir
from pydantic import BaseModel, ConfigDict

CONFIG_DIR_ENV = "TACTILE_TERRAIN_CONFIG_DIR"
APP_NAME = "tactile-terrain"


class PrinterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bed_mm: list[float]
    nozzle_mm: float
    grid_mm: float
    bed_margin_mm: float = 0.0
    max_print_hours: float = 0  # 0 = no limit
    max_stl_mb: float = 0  # 0 = no limit
    filament_density_g_cm3: float = 1.24
    slicer_config: str = ""
    submit_notes: str = ""


def _louisville_library() -> PrinterProfile:
    return PrinterProfile(
        bed_mm=[152, 152, 158],
        nozzle_mm=0.5,
        grid_mm=0.25,
        bed_margin_mm=5,
        max_print_hours=8,
        max_stl_mb=0,
        filament_density_g_cm3=1.24,
        slicer_config="",
        submit_notes="Request via the library form. One colour. Up to 10 days.",
    )


class UserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: str = "metric"
    models_dir: str = "~/TactileModels"
    active_profile: str = "standard"
    default_printer: str = "louisville-library"
    overpass_endpoint: str = "https://overpass-api.de/api/interpreter"
    printers: dict[str, PrinterProfile] = {"louisville-library": _louisville_library()}

    @property
    def models_path(self) -> Path:
        return Path(self.models_dir).expanduser()

    def printer(self, name: str) -> PrinterProfile:
        try:
            return self.printers[name]
        except KeyError:
            valid = ", ".join(sorted(self.printers)) or "(none configured)"
            raise KeyError(f"Unknown printer '{name}'. Valid names: {valid}") from None


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path(user_config_dir(APP_NAME))


def config_path() -> Path:
    return config_dir() / "config.toml"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"Cannot write {type(value).__name__} to TOML")


def _dump_toml(data: dict, prefix: str = "") -> str:
    lines = [f"{k} = {_toml_value(v)}" for k, v in data.items() if not isinstance(v, dict)]
    out = "\n".join(lines) + "\n" if lines else ""
    for key, value in data.items():
        if isinstance(value, dict):
            table = f"{prefix}{key}"
            out += f"\n[{table}]\n" + _dump_toml(value, table + ".")
    return out


def load_config() -> UserConfig:
    """Read config.toml, creating it with defaults on first load."""
    path = config_path()
    if not path.exists():
        cfg = UserConfig()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump_toml(cfg.model_dump()), encoding="utf-8")
        return cfg
    return UserConfig.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
