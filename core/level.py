"""Level system base interfaces.

Levels define how terrain/landing-sites are generated, what entities exist (e.g., the
lander), and custom progression/ending logic. A level is a lightweight
controller that configures the game world and can optionally react each frame.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.eval_goals import EVAL_GOAL_LANDING

if TYPE_CHECKING:
    from core.bot import Bot
    from core.ecs import Entity
    from core.landing_sites import LandingSiteSurfaceModel
    from core.physics import PhysicsEngine
    from core.terrain import Terrain


@dataclass
class LevelTraceConfig:
    enabled: bool = False
    sample_period_s: float = 0.25
    detail: str = "report"
    root_dir: str | None = None


@dataclass
class LevelRuntimeContext:
    level_name: str | None = None
    public_scenario_name: str | None = None
    scenario_name: str | None = None
    trace_selector_tag: str | None = None
    eval_target_pos: Any | None = None


@dataclass
class GameRunState:
    elapsed_time: float = 0.0
    landing_count: int = 0
    crash_count: int = 0
    distance_flown: float = 0.0
    fuel_consumed: float = 0.0
    overdrive_time: float = 0.0
    overdrive_excess: float = 0.0


def get_entity_mass(entity) -> float:
    from core.components import CargoHold, FuelTank, PhysicsState
    from core.ecs import require_component

    phys = require_component(entity, PhysicsState)
    tank = require_component(entity, FuelTank)
    cargo = entity.get_component(CargoHold)
    cargo_mass = cargo.effective_mass if cargo is not None else 0.0
    return phys.mass + tank.fuel * tank.density + cargo_mass


@dataclass
class LevelWorld:
    """Container for level-owned world state.

    Concrete types are imported under TYPE_CHECKING to avoid runtime import
    cycles while still providing proper annotations for static analysis.
    """

    terrain: Terrain
    sites: LandingSiteSurfaceModel
    lander: Entity
    actors: list[Entity] = field(default_factory=list)
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
    engine: PhysicsEngine | None = None
    scenario_name: str = ""
    eval_target_pos: Any | None = None
    trace_selector_tag: str | None = None
    trace_enabled: bool = False
    trace_sample_period_s: float = 0.25
    trace_detail: str = "report"
    trace_root_dir: str | None = None

    def __init__(self) -> None:
        self._runtime_context = LevelRuntimeContext(
            scenario_name=self.scenario_name or None,
            trace_selector_tag=self.trace_selector_tag,
            eval_target_pos=self.eval_target_pos,
        )
        self._trace_config = LevelTraceConfig(
            enabled=self.trace_enabled,
            sample_period_s=self.trace_sample_period_s,
            detail=self.trace_detail,
            root_dir=self.trace_root_dir,
        )

    def ensure_runtime_context(self) -> LevelRuntimeContext:
        context = getattr(self, "_runtime_context", None)
        if not isinstance(context, LevelRuntimeContext):
            context = LevelRuntimeContext(
                scenario_name=self.scenario_name or None,
                trace_selector_tag=self.trace_selector_tag,
                eval_target_pos=self.eval_target_pos,
            )
            setattr(self, "_runtime_context", context)
        return context

    def ensure_trace_config(self) -> LevelTraceConfig:
        config = getattr(self, "_trace_config", None)
        if not isinstance(config, LevelTraceConfig):
            config = LevelTraceConfig(
                enabled=self.trace_enabled,
                sample_period_s=self.trace_sample_period_s,
                detail=self.trace_detail,
                root_dir=self.trace_root_dir,
            )
            setattr(self, "_trace_config", config)
        return config

    def set_runtime_identity(
        self,
        *,
        level_name: str | None = None,
        public_scenario_name: str | None = None,
        scenario_name: str | None = None,
        trace_selector_tag: str | None = None,
        eval_target_pos: Any | None = None,
    ) -> None:
        context = self.ensure_runtime_context()
        if level_name is not None:
            context.level_name = level_name
        if public_scenario_name is not None:
            context.public_scenario_name = public_scenario_name
        if scenario_name is not None:
            self.scenario_name = scenario_name
            context.scenario_name = scenario_name
        if trace_selector_tag is not None:
            self.trace_selector_tag = trace_selector_tag
            context.trace_selector_tag = trace_selector_tag
        if eval_target_pos is not None:
            self.eval_target_pos = eval_target_pos
            context.eval_target_pos = eval_target_pos

    def set_trace_config(
        self,
        *,
        enabled: bool | None = None,
        sample_period_s: float | None = None,
        detail: str | None = None,
        root_dir: str | None = None,
    ) -> None:
        config = self.ensure_trace_config()
        if enabled is not None:
            self.trace_enabled = bool(enabled)
            config.enabled = bool(enabled)
        if sample_period_s is not None:
            self.trace_sample_period_s = float(sample_period_s)
            config.sample_period_s = float(sample_period_s)
        if detail is not None:
            self.trace_detail = str(detail)
            config.detail = str(detail)
        if root_dir is not None:
            self.trace_root_dir = root_dir
            config.root_dir = root_dir

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
        run_state = game.run_state
        if hasattr(game, "lander") and game.lander is not None:
            try:
                from core.components import LanderState

                ls = game.lander.get_component(LanderState)
                state = ls.state if ls is not None else None
            except Exception:
                state = None
        return {
            "time": run_state.elapsed_time,
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


__all__ = [
    "GameRunState",
    "get_entity_mass",
    "Level",
    "LevelRuntimeContext",
    "LevelTraceConfig",
    "LevelWorld",
]
