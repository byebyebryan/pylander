from __future__ import annotations

import random
from dataclasses import dataclass

import core.terrain as _terrain
from core.components import CargoHold
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
class FerryScenario:
    name: str
    dx: float | SampleRange


_SCENARIOS: tuple[FerryScenario, ...] = (
    FerryScenario(name="near", dx=SampleRange(150.0, 250.0)),
    FerryScenario(name="mid", dx=SampleRange(300.0, 500.0)),
    FerryScenario(name="far", dx=SampleRange(600.0, 1000.0)),
)
_SCENARIO_BY_NAME = {item.name: item for item in _SCENARIOS}
_DEFAULT_SCENARIO = "mid"
_QUICK_BENCHMARK_SCENARIOS: tuple[str, ...] = ("mid",)


class FerryLevel(PresetLevel):
    """Two-pad flat transfer setup for repeated point-to-point ferry runs."""

    default_bot_name = "ferry"
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

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key not in _SCENARIO_BY_NAME:
            known = ", ".join(sorted(_SCENARIO_BY_NAME))
            raise ValueError(f"Unknown ferry scenario '{name}'. Expected one of: {known}")
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
                uid="ferry_site_source",
                x=_SOURCE_PAD_X,
                size=110.0,
                award=100.0,
                fuel_price=8.0,
            ),
            SiteSpec(
                uid="ferry_site_dest",
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
        dest_site = self.sites.get_site("ferry_site_dest")
        if dest_site is not None:
            setattr(self, "eval_target_pos", Vector2(dest_site.x, dest_site.y))


def create_level() -> Level:
    return FerryLevel()
