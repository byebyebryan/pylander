from __future__ import annotations

from core.bot import Bot, BotAction, Sensors
from game import LanderGame
from levels import create_level as create_level_by_name
from runtime.bot_loop import BotLoopContext, update_bot_steps
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler


def _make_timers() -> LoopTimers:
    timers = LoopTimers(physics_dt=1.0 / 60.0, bot_dt=1.0 / 30.0, frame_dt=0.0)
    timers.time_accum_bot = timers.bot_dt
    return timers


def test_update_bot_steps_calls_update_and_records_tick() -> None:
    class _CountingBot(Bot):
        def __init__(self) -> None:
            super().__init__()
            self.update_calls = 0

        def update(self, dt: float, sensors: Sensors) -> BotAction:
            _ = dt, sensors
            self.update_calls += 1
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    bot = _CountingBot()
    game = LanderGame(level=create_level_by_name("flat"), seed=0, bot=bot, headless=True)
    profiler = BotLoopProfiler(enabled=True, interval_s=1.0, next_report_s=1.0)
    context = BotLoopContext(
        ecs_world=game.ecs_world,
        actor_bots=game.actor_bots,
        sensor_update_system=game.sensor_update_system,
        profiler=profiler,
        terrain=game.terrain,
    )

    controls = update_bot_steps(_make_timers(), context=context)
    uid = next(iter(game.actor_bots))
    assert controls[uid] == (0.0, 0.0, False)
    assert bot.update_calls == 1
    assert profiler.total.ticks == 1
    assert uid in profiler.by_bot


def test_bot_profiler_emits_total_and_percentiles() -> None:
    profiler = BotLoopProfiler(enabled=True, interval_s=1.0, next_report_s=1.0, log_lines=False)
    for update_s in (0.0010, 0.0015, 0.0020):
        profiler.record_tick("bot-1")
        profiler.record_passive_build("bot-1", 0.0005)
        profiler.record_bot_update("bot-1", update_s)
        profiler.record_tick_costs(
            "bot-1",
            passive_s=0.0005,
            update_s=update_s,
        )

    result: dict[str, float | int | bool] = {}
    profiler.apply_to_result(result)
    lines = profiler.maybe_report_lines(elapsed_s=5.0)

    assert result["bot_profile_enabled"] is True
    assert result["bot_profile_ticks"] == 3
    assert float(result["bot_profile_total_ms_per_tick"]) > 0.0
    assert float(result["bot_profile_total_ms_per_tick_p90"]) >= float(
        result["bot_profile_total_ms_per_tick"]
    )
    assert float(result["bot_profile_total_ms_per_tick_p99"]) >= float(
        result["bot_profile_total_ms_per_tick_p90"]
    )
    assert float(result["bot_profile_update_ms_per_tick_p99"]) >= float(
        result["bot_profile_update_ms_per_tick_p90"]
    )
    assert lines == []
