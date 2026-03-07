from __future__ import annotations

from dataclasses import dataclass

import core.terrain as _terrain
from core.components import CargoHold, Transform
from core.ecs import require_component
from core.eval_goals import EVAL_GOAL_LANDING, EVAL_GOAL_SETUP
from core.level import Level
from core.maths import Vector2

from levels.common import (
    PresetLevel,
    SiteSpec,
    apply_setup_transfer_result,
    get_mass,
    resolve_landed_site_uid,
)
from levels.scenario_common import ScenarioCatalogMixin

_SOURCE_PAD_X = 0.0
_SOURCE_SITE_UID = "setup_transfer_source"
_TARGET_SITE_UID = "setup_transfer_target"


@dataclass(frozen=True)
class SetupClimbScenario:
    name: str
    terrain_kind: str
    target_dx: float
    target_dy: float


_SCENARIOS: tuple[SetupClimbScenario, ...] = (
    SetupClimbScenario(name="low", terrain_kind="slope", target_dx=400.0, target_dy=200.0),
    SetupClimbScenario(name="mid", terrain_kind="slope", target_dx=400.0, target_dy=400.0),
    SetupClimbScenario(name="high", terrain_kind="slope", target_dx=400.0, target_dy=800.0),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "low",
    "mid",
    "high",
)


class SetupClimbLevel(ScenarioCatalogMixin, PresetLevel):
    """Pad-to-pad climb transfer with uphill destination profiles and no obstacles."""

    default_bot_name = "zem_zev"
    dynamic_site_enabled = False
    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS
    _benchmark_policy = "observe_only"
    _supported_eval_goals = (EVAL_GOAL_LANDING, EVAL_GOAL_SETUP)

    site_specs = ()
    spawn_x = _SOURCE_PAD_X
    spawn_clearance = 0.0
    spawn_x_jitter = 0.0
    site_x_jitter = 0.0

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        self._benchmark_random_mode = "sample"

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(f"Unknown benchmark mode '{mode}'. Expected one of: median, sample")
        self._benchmark_random_mode = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    @staticmethod
    def _scenario_slope(scenario: SetupClimbScenario) -> float:
        if scenario.terrain_kind != "slope":
            return 0.0
        return float(scenario.target_dy) / max(1e-6, float(scenario.target_dx))

    def _build_base_terrain(self, _seed: int):
        scenario = self._active_scenario()
        slope = self._scenario_slope(scenario)
        return _terrain.LodGridGenerator(lambda x: slope * x)

    def setup(self, game, seed: int) -> None:
        scenario = self._active_scenario()
        dest_x = _SOURCE_PAD_X + float(scenario.target_dx)
        slope = self._scenario_slope(scenario)
        self.site_specs = (
            SiteSpec(
                uid=_SOURCE_SITE_UID,
                x=_SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid=_TARGET_SITE_UID,
                x=dest_x,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
        )
        super().setup(game, seed)

        actor = self.world.actors[0]
        cargo = actor.get_component(CargoHold)
        if cargo is not None:
            cargo.cargo_mass = 0.0
        engine = getattr(self, "engine", None)
        if engine is not None and hasattr(engine, "set_lander_mass"):
            engine.set_lander_mass(get_mass(actor), uid=actor.uid)

        setattr(self, "scenario_name", scenario.name)
        setattr(
            self,
            "_scenario_params",
            {
                "terrain_kind": scenario.terrain_kind,
                "slope": slope,
                "dx": scenario.target_dx,
                "dy": scenario.target_dy,
            },
        )
        target_site = self.sites.get_site(_TARGET_SITE_UID)
        if target_site is not None:
            setattr(self, "eval_target_pos", Vector2(target_site.x, target_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        return resolve_landed_site_uid(self.site_specs, landed_x)

    def update(self, game, dt: float) -> None:
        _ = game, dt

    def end(self, game):
        result = super().end(game)
        actor = self.world.actors[0]

        state = str(result.get("state", "unknown"))
        landed_uid: str | None = None
        if state == "landed":
            trans = require_component(actor, Transform)
            landed_uid = self._resolve_landed_site_uid(float(trans.pos.x))

        return apply_setup_transfer_result(
            result,
            state=state,
            landed_uid=landed_uid,
            source_uid=_SOURCE_SITE_UID,
            target_uid=_TARGET_SITE_UID,
        )


def create_level() -> Level:
    return SetupClimbLevel()
