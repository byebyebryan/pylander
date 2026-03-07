from __future__ import annotations

import random
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
from levels.scenario_common import (
    SampleRange,
    ScenarioCatalogMixin,
    has_randomized_values,
    resolve_sample_value,
)

_SOURCE_PAD_X = 0.0
_SOURCE_SITE_UID = "setup_transfer_source"
_TARGET_SITE_UID = "setup_transfer_target"


@dataclass(frozen=True)
class SetupFlatScenario:
    name: str
    dx: float | SampleRange


_SCENARIOS: tuple[SetupFlatScenario, ...] = (
    SetupFlatScenario(name="near", dx=SampleRange(150.0, 250.0)),
    SetupFlatScenario(name="mid", dx=SampleRange(300.0, 500.0)),
    SetupFlatScenario(name="far", dx=SampleRange(600.0, 1000.0)),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_SMOKE_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)


class SetupFlatLevel(ScenarioCatalogMixin, PresetLevel):
    """Pad-to-pad flat transfer setup for setup-phase tuning."""

    default_bot_name = "zem_zev"
    dynamic_site_enabled = False
    _scenario_by_name = _SCENARIO_BY_NAME
    _default_scenario_name = _DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = _SMOKE_BENCHMARK_SCENARIOS
    _quick_benchmark_scenarios = _QUICK_BENCHMARK_SCENARIOS
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
        scenario = _SCENARIO_BY_NAME[self._eval_scenario_name]
        return has_randomized_values((scenario.dx,))

    def _build_base_terrain(self, _seed: int):
        return _terrain.LodGridGenerator(lambda _x: 0.0)

    def setup(self, game, seed: int) -> None:
        scenario = self._active_scenario()
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
                "dx": dest_dx,
            },
        )
        dest_site = self.sites.get_site(_TARGET_SITE_UID)
        if dest_site is not None:
            setattr(self, "eval_target_pos", Vector2(dest_site.x, dest_site.y))

    def _resolve_landed_site_uid(self, landed_x: float) -> str | None:
        return resolve_landed_site_uid(self.site_specs, landed_x)

    def end(self, game):
        result = super().end(game)
        state = str(result.get("state", "unknown"))
        landed_uid: str | None = None
        if state == "landed":
            actor = self.world.actors[0]
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
    return SetupFlatLevel()
