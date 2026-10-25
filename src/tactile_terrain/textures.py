"""Area textures (displacement functions). The registry is empty in Phase 1."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class Texture(Protocol):
    def displacement(self, x_mm: np.ndarray, y_mm: np.ndarray) -> np.ndarray:
        """Height offset in mm at each print-space point."""
        ...
