from __future__ import annotations

import random
from dataclasses import dataclass

import core.terrain as _terrain
from core.components import CargoHold, Transform
from core.ecs import require_component
from core.level_capabilities import BenchmarkScenarioSets, LevelBenchmarkProfile
from core.level import Level
from core.maths import Vector2
from levels.common import PresetLevel, SiteSpec, get_mass
from levels.scenario_common import (
    SampleRange,
    has_randomized_values,
    resolve_sample_value,
)

_SOURCE_PAD_X = 0.0


@dataclass(frozen=True)
class LaunchScenario:
    name: str
    dx: float | SampleRange


_SCENARIOS: tuple[LaunchScenario, ...] = (
    LaunchScenario(name="near", dx=SampleRange(150.0, 250.0)),
    LaunchScenario(name="mid", dx=SampleRange(300.0, 500.0)),
    LaunchScenario(name="far", dx=SampleRange(600.0, 1000.0)),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)


class LaunchLevel(PresetLevel):
    """Two-pad flat transfer setup for repeated point-to-point launch runs."""

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
            policy="normal",
            scenarios=BenchmarkScenarioSets(smoke=smoke, quick=quick, full=full),
        )

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown launch scenario '{name}'. Expected one of: {known}")
        self._eval_scenario_name = key

    def set_benchmark_mode(self, mode: str) -> None:
        key = str(mode or "sample").strip().lower()
        if key not in {"median", "sample"}:
            raise ValueError(f"Unknown benchmark mode '{mode}'. Expected one of: median, sample")
        self._benchmark_random_mode = key

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values((scenario.dx,))

    def _build_base_terrain(self, _seed: int):
        return _terrain.LodGridGenerator(lambda _x: 0.0)

    def setup(self, game, seed: int) -> None:
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        scenario_name_hash = sum(ord(ch) for ch in scenario.name)
        rng = random.Random(seed ^ (scenario_name_hash << 1))
        dest_dx = resolve_sample_value(
            scenario.dx,
            mode="median" if self._benchmark_random_mode == "median" else "sample",
            rng=rng,
        )
        dest_x = _SOURCE_PAD_X + dest_dx
        self.site_specs = (
            SiteSpec(
                uid="launch_site_source",
                x=_SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid="launch_site_dest",
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
                "dx": dest_dx,
            },
        )
        dest_site = self.sites.get_site("launch_site_dest")
        if dest_site is not None:
            setattr(self, "eval_target_pos", Vector2(dest_site.x, dest_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        for spec in self.site_specs:
            half = 0.5 * float(spec.size)
            distance = abs(float(landed_x) - float(spec.x))
            if distance <= half + 1e-6:
                return spec.uid
        return None

    def end(self, game):
        result = super().end(game)
        state = str(result.get("state", "unknown"))
        landed_uid: str | None = None
        if state == "landed":
            actor = self.world.actors[0]
            trans = require_component(actor, Transform)
            landed_uid = self._resolve_landed_site_uid(float(trans.pos.x))
        launch_arrived = state == "landed" and landed_uid == "launch_site_dest"
        result["launch_arrived"] = launch_arrived
        result["launch_landed_site_uid"] = landed_uid
        result["success"] = launch_arrived
        if launch_arrived:
            result["failure_mode"] = "none"
        elif state == "landed":
            result["failure_mode"] = "wrong_pad"
        else:
            result["failure_mode"] = state
        return result


def create_level() -> Level:
    return LaunchLevel()
