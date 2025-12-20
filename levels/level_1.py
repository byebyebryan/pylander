from __future__ import annotations

import terrain as _terrain
from landers import create_lander
from level import Level, LevelWorld
from levels.common import should_end_default, compute_score_default
from physics import PhysicsEngine


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
            ]
        )
        targets = _terrain.TargetManager(tgt_gen)
        terrain = _terrain.AddHeightModifier(
            _terrain.LodGridGenerator(height_func), targets.height_modifier
        )

        start_x = 0.0
        start_y = terrain(start_x) + 100.0
        # Create lander via dynamic loader; default to "classic" when unspecified
        lander_name = getattr(self, "lander_name", "classic")
        lander = create_lander(lander_name)
        lander.start_x = start_x
        lander.y = start_y

        # Create physics engine and attach lander body
        engine = PhysicsEngine(
            height_sampler=terrain,
            gravity=(0.0, -9.8),
            segment_step=10.0,
            half_width=12000.0,
        )
        # Attach using provided physics polygons when available; fallback to triangle
        polys = lander.get_physics_polygons()
        if polys and hasattr(engine, "attach_lander_from_polygons"):
            engine.attach_lander_from_polygons(
                polygons=polys,
                mass=lander.get_mass(),
                friction=0.9,
                elasticity=0.0,
                start_x=start_x,
                start_y=start_y,
                start_angle=lander.rotation,
            )
        else:
            engine.attach_lander(
                width=lander.width,
                height=lander.height,
                mass=lander.get_mass(),
                friction=0.9,
                elasticity=0.0,
                start_x=start_x,
                start_y=start_y,
                start_angle=lander.rotation,
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
            "state": game.lander.state,
            "landing_count": landing_count,
            "crash_count": crash_count,
            "credits": game.lander.credits,
            "fuel": game.lander.fuel,
            "score": score,
        }

        # Plotting handled by Plotter in game; any plot artifacts will be merged
        # into the final result by the game loop.

        return result


def create_level() -> Level:
    return GentleStartLevel()
