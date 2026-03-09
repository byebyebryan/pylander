"""Level system base interfaces.

Levels define how terrain/landing-sites are generated, what entities exist (e.g., the
lander), and custom progression/ending logic. A level is a lightweight
controller that configures the game world and can optionally react each frame.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.eval_goals import EVAL_GOAL_LANDING

if TYPE_CHECKING:
    from core.bot import Bot
    from core.ecs import Entity
    from core.landing_sites import LandingSiteSurfaceModel
    from core.lander import Lander
    from core.terrain import Terrain

@dataclass
class LevelWorld:
    """Container for level-owned world state.

    Concrete types are imported under TYPE_CHECKING to avoid runtime import
    cycles while still providing proper annotations for static analysis.
    """

    terrain: Terrain
    sites: LandingSiteSurfaceModel
    lander: Lander
    actors: list[Lander] = field(default_factory=list)
    primary_actor_uid: str | None = None
    site_entities: list[Entity] = field(default_factory=list)
    extra_entities: list[Entity] = field(default_factory=list)
    actor_bots: dict[str, Bot] = field(default_factory=dict)


class Level(ABC):
    """Abstract base class for game levels.

    Contract:
    - setup(game, seed): construct and assign self.world (terrain, sites, lander)
    - start(game): optional hook when run() begins
    - update(game, dt): per-frame hook for custom logic
    - should_end(game): return True to end the run (default delegates to is_complete)
    - end(game): return a result dict on shutdown
    """

    world: LevelWorld | None = None

    @abstractmethod
    def setup(self, game, seed: int) -> None:
        """Construct terrain/sites/lander and assign self.world."""
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
        state = None
        if hasattr(game, "lander") and game.lander is not None:
            try:
                from core.components import LanderState

                ls = game.lander.get_component(LanderState)
                state = ls.state if ls is not None else None
            except Exception:
                state = None
        return {
            "time": getattr(game, "_elapsed_time", 0.0),
            "state": state,
        }

    def supported_eval_goals(self) -> tuple[str, ...]:
        """Return eval goals supported by this level."""
        return (EVAL_GOAL_LANDING,)

    # Convenience properties forwarding to world
    @property
    def terrain(self):
        return None if self.world is None else self.world.terrain

    @property
    def sites(self):
        return None if self.world is None else self.world.sites

    @property
    def lander(self):
        if self.world is None:
            return None
        if getattr(self.world, "primary_actor_uid", None):
            for actor in getattr(self.world, "actors", []):
                if actor.uid == self.world.primary_actor_uid:
                    return actor
        return self.world.lander

    @property
    def actors(self):
        if self.world is None:
            return []
        actors = getattr(self.world, "actors", None)
        if actors:
            return actors
        return [self.world.lander] if self.world.lander is not None else []


__all__ = ["Level", "LevelWorld"]
