"""On-disk stage cache keyed by a hash of each stage's inputs."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any


def stage_key(name: str, spec_slice: Any, upstream_key: str) -> str:
    payload = json.dumps([name, spec_slice, upstream_key], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


class StageCache:
    def __init__(self, model_dir: Path) -> None:
        self.dir = Path(model_dir) / "cache" / "stages"

    def _path(self, name: str, key: str) -> Path:
        return self.dir / f"{name}-{key}.pkl"

    def load(self, name: str, key: str) -> tuple[bool, Any]:
        path = self._path(name, key)
        if not path.exists():
            return False, None
        try:
            return True, pickle.loads(path.read_bytes())
        except (pickle.UnpicklingError, EOFError, AttributeError, ImportError):
            return False, None  # unreadable cache entries are rebuilt

    def store(self, name: str, key: str, result: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(name, key).write_bytes(pickle.dumps(result))
