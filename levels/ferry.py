from __future__ import annotations

import core.terrain as _terrain
from core.components import CargoHold
from core.level import Level
from core.maths import Vector2
from levels.common import PresetLevel, SiteSpec, get_mass

_FERRY_SCENARIO_NAME = "default"
_SOURCE_PAD_X = 0.0
_DEST_PAD_X = 800.0


class FerryLevel(PresetLevel):
    """Two-pad flat transfer setup for repeated point-to-point ferry runs."""

    default_bot_name = "ferry"
    dynamic_site_enabled = False

    site_specs = (
        SiteSpec(
            uid="ferry_site_source",
            x=_SOURCE_PAD_X,
            size=110.0,
            award=100.0,
            fuel_price=8.0,
        ),
        SiteSpec(
            uid="ferry_site_dest",
            x=_DEST_PAD_X,
            size=110.0,
            award=100.0,
            fuel_price=8.0,
        ),
    )
    spawn_x = _SOURCE_PAD_X
    spawn_clearance = 0.0
    spawn_x_jitter = 0.0
    site_x_jitter = 0.0

    @staticmethod
    def list_batch_scenarios() -> list[str]:
        return [_FERRY_SCENARIO_NAME]

    @staticmethod
    def list_quick_benchmark_scenarios() -> list[str]:
        return [_FERRY_SCENARIO_NAME]

    def set_eval_scenario(self, name: str) -> None:
        key = str(name).strip().lower()
        if key != _FERRY_SCENARIO_NAME:
            raise ValueError(
                f"Unknown ferry scenario '{name}'. Expected one of: {_FERRY_SCENARIO_NAME}"
            )

    def _build_base_terrain(self, _seed: int):
        return _terrain.LodGridGenerator(lambda _x: 0.0)

    def setup(self, game, seed: int) -> None:
        super().setup(game, seed)
        actor = self.world.actors[0]
        cargo = actor.get_component(CargoHold)
        if cargo is not None:
            cargo.cargo_mass = 0.0
        engine = getattr(self, "engine", None)
        if engine is not None and hasattr(engine, "set_lander_mass"):
            engine.set_lander_mass(get_mass(actor), uid=actor.uid)
        setattr(self, "scenario_name", _FERRY_SCENARIO_NAME)
        dest_site = self.sites.get_site("ferry_site_dest")
        if dest_site is not None:
            setattr(self, "eval_target_pos", Vector2(dest_site.x, dest_site.y))


def create_level() -> Level:
    return FerryLevel()
