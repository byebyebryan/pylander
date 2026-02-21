from __future__ import annotations

from core.bot import Bot, BotAction
from core.components import LanderState
from core.landing_sites import LandingSiteSurfaceModel
from core.maths import Vector2
from core.lander import Lander
from core.level import Level, LevelWorld
from game import LanderGame


class _FlatTerrain:
    def __call__(self, _x: float, lod: int = 0) -> float:
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0


class _PassiveBot(Bot):
    def update(self, dt, passive, active) -> BotAction:  # noqa: D401
        return BotAction(target_thrust=0.0, target_angle=passive.angle, refuel=False)


class _ShortLevel(Level):
    def __init__(self, stop_after_updates: int = 3):
        self.stop_after_updates = stop_after_updates
        self.update_calls = 0

    def setup(self, _game, seed: int) -> None:
        _ = seed
        self.world = LevelWorld(
            terrain=_FlatTerrain(),
            sites=LandingSiteSurfaceModel(),
            lander=Lander(start_pos=Vector2(0.0, 100.0)),
        )

    def update(self, game, dt: float) -> None:
        _ = game, dt
        self.update_calls += 1

    def should_end(self, game) -> bool:
        _ = game
        return self.update_calls >= self.stop_after_updates

    def end(self, game):
        ls = game.lander.get_component(LanderState)
        if ls is None:
            raise RuntimeError("Lander missing LanderState component")
        return {
            "updates": self.update_calls,
            "elapsed_time": getattr(game, "_elapsed_time", 0.0),
            "state": ls.state,
        }


class _FakeEngine:
    def __init__(self):
        self.pose = (Vector2(0.0, 100.0), 0.0)
        self.velocity = (Vector2(0.0, 0.0), 0.0)

    def set_lander_mass(self, _mass: float) -> None:
        pass

    def set_lander_controls(self, _thrust_force: float, _angle: float) -> None:
        pass

    def override(self, _angle: float) -> None:
        pass

    def apply_force(self, _force: Vector2, _point: Vector2 | None = None) -> None:
        pass

    def step(self, _dt: float) -> None:
        pass

    def get_pose(self) -> tuple[Vector2, float]:
        return self.pose

    def get_velocity(self) -> tuple[Vector2, float]:
        return self.velocity

    def get_contact_report(self) -> dict:
        return {"colliding": False, "normal": None, "rel_speed": 0.0, "point": None}

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None:
        _ = clear_velocity
        self.pose = (Vector2(pos), 0.0 if angle is None else angle)

    def raycast(self, _origin: Vector2, _angle: float, _max_distance: float) -> dict:
        return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}


def test_headless_mode_requires_bot() -> None:
    level = _ShortLevel()
    try:
        LanderGame(level=level, headless=True)
    except ValueError as exc:
        assert "requires a bot" in str(exc)
    else:
        raise AssertionError("Expected ValueError when running headless without a bot")


def test_game_run_returns_level_result_and_advances_time() -> None:
    level = _ShortLevel(stop_after_updates=3)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)

    result = game.run(print_freq=0, max_steps=100)

    assert result["updates"] == 3
    assert result["state"] == "flying"
    assert result["elapsed_time"] > 0.0
    assert game._elapsed_time == result["elapsed_time"]


def test_state_transition_runs_once_per_frame_with_engine_enabled() -> None:
    level = _ShortLevel(stop_after_updates=999)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)
    game.engine_adapter._engine = _FakeEngine()

    calls = {"count": 0}
    original_update = game.state_transition_system.update

    def _counting_update(dt: float) -> None:
        calls["count"] += 1
        original_update(dt)

    game.state_transition_system.update = _counting_update
    result = game.run(print_freq=0, max_steps=3)
    assert result["updates"] == 3
    assert calls["count"] == 3
