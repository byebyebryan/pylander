from __future__ import annotations

import core.terrain as _terrain
from core.components import FuelTank, LanderGeometry, LanderState, PhysicsState, Transform, Wallet
from core.maths import Vector2
from landers import create_lander
from core.level import Level, LevelWorld
from levels.common import should_end_default, compute_score_default
from core.physics import PhysicsEngine


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_mass(entity) -> float:
    phys = _require_component(entity, PhysicsState)
    tank = _require_component(entity, FuelTank)
    return phys.mass + tank.fuel * tank.density


class GentleStartLevel(Level):
    """Baseline level: simplex terrain, scattered targets, start near origin."""

    def setup(self, _game, seed: int) -> None:
        height_func = _terrain.SimplexNoiseGenerator(seed=seed)

        tgt_gen = _terrain.CompositeTargetGenerator(
            [
                _terrain.RandomDistanceTargetGenerator(seed=seed),
                _terrain.TargetHeightModifier(height_func, seed=seed),
                _terrain.TargetSizeModifier(seed=seed),
                _terrain.TargetAwardsModifier(seed=seed),
                _terrain.TargetFuelPriceModifier(seed=seed),
            ]
        )
        targets = _terrain.TargetManager(tgt_gen)
        terrain = _terrain.AddHeightModifier(
            _terrain.LodGridGenerator(height_func), targets.height_modifier
        )

        start_pos = Vector2(0.0, terrain(0.0) + 100.0)
        # Create lander via dynamic loader; default to "classic" when unspecified
        lander_name = getattr(self, "lander_name", "classic")
        lander = create_lander(lander_name)
        lander.start_pos = Vector2(start_pos)
        trans = _require_component(lander, Transform)
        geo = _require_component(lander, LanderGeometry)
        trans.pos = Vector2(start_pos)

        # Create physics engine and attach lander body
        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        engine.attach_lander(
            width=geo.width,
            height=geo.height,
            mass=_get_mass(lander),
            friction=0.9,
            elasticity=0.0,
            start_pos=start_pos,
            start_angle=trans.rotation,
        )

        self.world = LevelWorld(terrain=terrain, targets=targets, lander=lander)
        # Expose engine on the level for the game loop
        setattr(self, "engine", engine)

    def should_end(self, game) -> bool:
        return should_end_default(
            game,
            stop_on_crash=getattr(self, "stop_on_crash", False),
            stop_on_first_land=getattr(self, "stop_on_first_land", False),
            stop_on_out_of_fuel=getattr(self, "stop_on_out_of_fuel", False),
            max_time=getattr(self, "max_time", None),
        )

    def end(self, game):
        # compute simple stats
        # We derive landings/crashes from game loop counters if present; if not available, approximate from state transitions would be needed.
        landing_count = getattr(game, "_landing_count", 0)
        crash_count = getattr(game, "_crash_count", 0)
        score = compute_score_default(
            game,
            landing_count,
            crash_count,
            credits_score=1.0,
            fuel_score=10.0,
            landing_score=100.0,
            crash_penalty=-200.0,
        )

        result = {
            "time": getattr(game, "_elapsed_time", 0.0),
            "state": _require_component(game.lander, LanderState).state,
            "landing_count": landing_count,
            "crash_count": crash_count,
            "credits": _require_component(game.lander, Wallet).credits,
            "fuel": _require_component(game.lander, FuelTank).fuel,
            "score": score,
        }

        # Plotting handled by Plotter in game; any plot artifacts will be merged
        # into the final result by the game loop.

        return result


def create_level() -> Level:
    return GentleStartLevel()
