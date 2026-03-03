from __future__ import annotations

from core.bot import Bot, BotAction, PassiveSensors, QueryBot
from core.bot_queries import BotQueryTerrainProfile
from game import LanderGame
from levels import create_level as create_level_by_name
from runtime.bot_loop import BotLoopContext, update_bot_steps
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler


def _make_timers() -> LoopTimers:
    timers = LoopTimers(physics_dt=1.0 / 60.0, bot_dt=1.0 / 30.0, frame_dt=0.0)
    timers.time_accum_bot = timers.bot_dt
    return timers


def test_update_bot_steps_query_bot_path_records_query_stats() -> None:
    class _CountingQueryBot(QueryBot):
        def __init__(self) -> None:
            super().__init__()
            self.plan_calls = 0
            self.act_calls = 0

        def plan(self, dt: float, passive: PassiveSensors):
            _ = dt, passive
            self.plan_calls += 1
            return [BotQueryTerrainProfile(id="tp", x_start=-50.0, x_end=50.0, samples=5)]

        def act(self, dt: float, passive: PassiveSensors, results):
            _ = dt, passive, results
            self.act_calls += 1
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    bot = _CountingQueryBot()
    game = LanderGame(level=create_level_by_name("flat"), seed=0, bot=bot, headless=True)
    profiler = BotLoopProfiler(enabled=True, interval_s=1.0, next_report_s=1.0)
    context = BotLoopContext(
        ecs_world=game.ecs_world,
        actor_bots=game.actor_bots,
        sensor_update_system=game.sensor_update_system,
        profiler=profiler,
        terrain=game.terrain,
        engine_adapter=game.engine_adapter,
    )

    controls = update_bot_steps(_make_timers(), context=context)
    uid = next(iter(game.actor_bots))
    assert controls[uid] == (0.0, 0.0, False)
    assert bot.plan_calls == 1
    assert bot.act_calls == 1
    assert profiler.total.ticks == 1
    assert profiler.total.query_total == 1
    assert profiler.total.query_terrain_profile == 1
    assert profiler.total.query_raycast == 0
    assert profiler.total.query_ballistic == 0


def test_update_bot_steps_legacy_bot_path_uses_active_sensor_bucket() -> None:
    class _LegacyBot(Bot):
        def __init__(self) -> None:
            super().__init__()
            self.update_calls = 0

        def update(self, dt: float, passive: PassiveSensors, active) -> BotAction:
            _ = dt, passive
            self.update_calls += 1
            _ = active.terrain_height(passive.x)
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    bot = _LegacyBot()
    game = LanderGame(level=create_level_by_name("flat"), seed=0, bot=bot, headless=True)
    profiler = BotLoopProfiler(enabled=True, interval_s=1.0, next_report_s=1.0)
    context = BotLoopContext(
        ecs_world=game.ecs_world,
        actor_bots=game.actor_bots,
        sensor_update_system=game.sensor_update_system,
        profiler=profiler,
        terrain=game.terrain,
        engine_adapter=game.engine_adapter,
    )

    controls = update_bot_steps(_make_timers(), context=context)
    uid = next(iter(game.actor_bots))
    assert controls[uid] == (0.0, 0.0, False)
    assert bot.update_calls == 1
    assert profiler.total.ticks == 1
    assert profiler.total.query_total == 0
    assert uid in profiler.by_bot
