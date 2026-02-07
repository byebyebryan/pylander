"""Level system base interfaces.

Levels define how terrain/targets are generated, what entities exist (e.g., the
lander), and custom progression/ending logic. A level is a lightweight
controller that configures the game world and can optionally react each frame.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from core.lander import Lander
from core.terrain import Terrain
from core.maths import Vector2


@dataclass
class LevelWorld:
    """Container for level-owned world state.

    Types are intentionally loose here to avoid cross-module import cycles.
    """

    terrain: Any
    targets: Any
    lander: Any  # Lander


class Level(ABC):
    """Abstract base class for game levels.

    Contract:
    - setup(game, seed): construct and assign self.world (terrain, targets, lander)
    - start(game): optional hook when run() begins
    - update(game, dt): per-frame hook for custom logic
    - should_end(game): return True to end the run (default delegates to is_complete)
    - end(game): return a result dict on shutdown
    """

    world: LevelWorld | None = None

    @abstractmethod
    def setup(self, game, seed: int) -> None:
        """Construct terrain/targets/lander and assign self.world."""
        raise NotImplementedError

    def start(self, game) -> None:  # pragma: no cover - default no-op
        pass

    def update(self, game, dt: float) -> None:  # pragma: no cover - default no-op
        pass

    def should_end(self, _game) -> bool:
        """Return True when the level should end (default: never)."""
        # Back-compat with older is_complete implementations
        return False

    def end(self, game):  # pragma: no cover - default no-op
        """Finalize level and return a result dict."""
        return {
            "time": getattr(game, "_elapsed_time", 0.0),
            "state": getattr(game.lander, "state", None),
        }

    # Convenience properties forwarding to world
    @property
    def terrain(self):
        return None if self.world is None else self.world.terrain

    @property
    def targets(self):
        return None if self.world is None else self.world.targets

    @property
    def lander(self):
        return None if self.world is None else self.world.lander


__all__ = ["Level", "LevelWorld"]
