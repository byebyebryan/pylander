from __future__ import annotations

from core.bot import Bot, BotAction
from core.maths import Vector2
from core.lander import Lander
from core.level import Level, LevelWorld
from game import LanderGame


class _FlatTerrain:
    def __call__(self, _x: float, lod: int = 0) -> float:
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0


class _EmptyTargets:
    def get_targets(self, _span) -> list:
        return []


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
            targets=_EmptyTargets(),
            lander=Lander(start_pos=Vector2(0.0, 100.0)),
        )

    def update(self, game, dt: float) -> None:
        _ = game, dt
        self.update_calls += 1

    def should_end(self, game) -> bool:
        _ = game
        return self.update_calls >= self.stop_after_updates

    def end(self, game):
        return {
            "updates": self.update_calls,
            "elapsed_time": getattr(game, "_elapsed_time", 0.0),
            "state": game.lander.state,
        }


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
