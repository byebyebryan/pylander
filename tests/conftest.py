from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FlatTerrain:
    """Shared flat-terrain mock for tests."""

    def __call__(self, _x: float, lod: int = 0) -> float:
        _ = lod
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0
