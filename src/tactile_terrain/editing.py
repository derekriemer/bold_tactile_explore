"""Spec edits for update_model: JSON merge-patch plus the shortcuts, and a readable diff."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

SHORTCUTS = ("z_multiply", "crop_percent", "drop_feature", "revert_to")
LAST_WORDS = ("last", "previous")  # revert_to values meaning the newest earlier version
CROP_EDGES = ("north", "south", "east", "west")
DIFF_VALUE_CHARS = 80
PERCENT = 100


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge-patch: objects merge, null deletes a key, anything else replaces."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def backup_numbers(model_dir: Path) -> list[int]:
    found = []
    for path in model_dir.glob("spec.*.json"):
        match = re.fullmatch(r"spec\.(\d+)\.json", path.name)
        if match:
            found.append(int(match.group(1)))
    return sorted(found)


def _crop(bbox: list[float], percents: dict[str, float]) -> list[float]:
    unknown = set(percents) - set(CROP_EDGES)
    if unknown:
        raise ValueError(
            f"crop_percent edges must be {', '.join(CROP_EDGES)}; got {', '.join(sorted(unknown))}"
        )
    west, south, east, north = (float(v) for v in bbox)
    width, height = east - west, north - south
    pct = {edge: float(percents.get(edge, 0)) / PERCENT for edge in CROP_EDGES}
    if any(not 0 <= v < 1 for v in pct.values()) or pct["east"] + pct["west"] >= 1:
        raise ValueError("crop_percent values must be 0 or more, and each axis must keep some area")
    if pct["north"] + pct["south"] >= 1:
        raise ValueError("crop_percent values must leave some area on the north-south axis")
    return [
        west + pct["west"] * width,
        south + pct["south"] * height,
        east - pct["east"] * width,
        north - pct["north"] * height,
    ]


def apply_changes(current: dict[str, Any], changes: dict[str, Any], model_dir: Path) -> dict:
    """Return the new spec dict. Shortcuts apply after the merge-patch; revert_to goes first."""
    changes = dict(changes)
    revert = changes.pop("revert_to", None)
    multiply = changes.pop("z_multiply", None)
    crop = changes.pop("crop_percent", None)
    drop = changes.pop("drop_feature", None)

    new = copy.deepcopy(current)
    if revert in LAST_WORDS:  # undo the most recent edit (and, run again, redo it)
        numbers = backup_numbers(model_dir)
        if not numbers:
            raise FileNotFoundError("Nothing to undo: this model has no earlier versions.")
        revert = numbers[-1]
    if revert is not None:
        earlier = model_dir / f"spec.{int(revert)}.json"
        if not earlier.exists():
            have = ", ".join(str(n) for n in backup_numbers(model_dir)) or "none"
            raise FileNotFoundError(f"No earlier version {revert}. Versions available: {have}.")
        new = json.loads(earlier.read_text(encoding="utf-8"))
    new = merge_patch(new, changes)
    if multiply is not None:
        new["print"]["z_exaggeration"] = new["print"].get("z_exaggeration", 1.0) * multiply
    if crop is not None:
        new["area"]["bbox"] = _crop(new["area"]["bbox"], crop)
    if drop is not None:
        kept = [f for f in new.get("features", []) if f.get("type") != drop]
        if len(kept) == len(new.get("features", [])):
            have = ", ".join(sorted({f.get("type", "") for f in new.get("features", [])}))
            raise ValueError(f"No feature of type {drop} to drop. Feature types: {have}.")
        new["features"] = kept
    return new


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict) and value:
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{path}.{key}" if path else key))
        return out
    return {path: value}


def _show(value: Any) -> str:
    text = "(none)" if value is None else json.dumps(value)
    return text if len(text) <= DIFF_VALUE_CHARS else text[:DIFF_VALUE_CHARS] + "..."


def diff_lines(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    before, after = _flatten(old), _flatten(new)
    lines = []
    for key in sorted(before.keys() | after.keys()):
        if before.get(key) != after.get(key):
            lines.append(f"{key}: {_show(before.get(key))} → {_show(after.get(key))}")
    return lines
