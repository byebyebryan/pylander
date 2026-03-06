from __future__ import annotations

import core.terrain as _terrain
from core.components import CargoHold, Transform
from core.ecs import require_component
from core.eval_goals import EVAL_GOAL_LANDING, EVAL_GOAL_SETUP
from core.level_capabilities import BenchmarkScenarioSets, LevelBenchmarkProfile
from core.level import Level
from core.maths import Vector2
from dataclasses import dataclass

from levels.common import PresetLevel, SiteSpec, get_mass

_SOURCE_PAD_X = 0.0


@dataclass(frozen=True)
class ClimbScenario:
    name: str
    terrain_kind: str
    target_dx: float
    target_dy: float


_SCENARIOS: tuple[ClimbScenario, ...] = (
    ClimbScenario(name="slope_low", terrain_kind="slope", target_dx=400.0, target_dy=200.0),
    ClimbScenario(name="slope_mid", terrain_kind="slope", target_dx=400.0, target_dy=400.0),
    ClimbScenario(name="slope_high", terrain_kind="slope", target_dx=400.0, target_dy=800.0),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "slope_mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("slope_mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = (
    "slope_low",
    "slope_mid",
    "slope_high",
)
class ClimbLevel(PresetLevel):
    """Pad-to-pad climb transfer with uphill destination profiles and no obstacles."""

    default_bot_name = "zem_zev"
    dynamic_site_enabled = False

    site_specs = ()
    spawn_x = _SOURCE_PAD_X
    spawn_clearance = 0.0
    spawn_x_jitter = 0.0
    site_x_jitter = 0.0

    def __init__(self) -> None:
        super().__init__()
        self._eval_scenario_name = _DEFAULT_SCENARIO
        self._benchmark_random_mode = "sample"

    @staticmethod
    def supported_eval_goals() -> tuple[str, ...]:
        return (EVAL_GOAL_LANDING, EVAL_GOAL_SETUP)

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [item.name for item in _SCENARIOS]

    @staticmethod
    def list_quick_benchmark_scenarios() -> list[str]:
        return [name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME]

    @staticmethod
    def benchmark_profile() -> LevelBenchmarkProfile:
        full = tuple(item.name for item in _SCENARIOS)
        quick = tuple(name for name in _QUICK_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME)
        smoke = tuple(name for name in _SMOKE_BENCHMARK_SCENARIOS if name in _SCENARIO_BY_NAME)
        return LevelBenchmarkProfile(
            policy="observe_only",
            scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
        )

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown climb scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(f"Unknown benchmark mode '{mode}'. Expected one of: median, sample")
        self._benchmark_random_mode = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return False

    def _active_scenario(self) -> ClimbScenario:
        return _SCENARIO_BY_NAME[self._eval_scenario_name]

    @staticmethod
    def _scenario_slope(scenario: ClimbScenario) -> float:
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
        target_mode = "flush_flatten"
        self.site_specs = (
            SiteSpec(
                uid="climb_site_source",
                x=_SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid="climb_site_target",
                x=dest_x,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
                terrain_mode=target_mode,
                terrain_bound=True,
                y_offset=0.0,
                support_height=40.0,
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
                "target_mode": target_mode,
            },
        )
        target_site = self.sites.get_site("climb_site_target")
        if target_site is not None:
            setattr(self, "eval_target_pos", Vector2(target_site.x, target_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        for spec in self.site_specs:
            half = 0.5 * float(spec.size)
            distance = abs(float(landed_x) - float(spec.x))
            if distance <= half + 1e-6:
                return spec.uid
        return None

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

        climb_arrived = state == "landed" and landed_uid == "climb_site_target"
        result["climb_arrived"] = climb_arrived
        result["climb_landed_site_uid"] = landed_uid

        result["success"] = climb_arrived
        if climb_arrived:
            result["failure_mode"] = "none"
        elif state == "landed":
            result["failure_mode"] = "wrong_pad"
        else:
            result["failure_mode"] = state
        return result


def create_level() -> Level:
    return ClimbLevel()
