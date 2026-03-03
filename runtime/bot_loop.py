from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from core.bot import Bot, BotAction, QueryBot
from core.components import LanderState
from runtime.bot_query_eval import evaluate_bot_queries
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler
from runtime.sensors import build_active_sensors, build_passive_sensors
from utils.protocols import ControlTuple


@dataclass
class BotLoopContext:
    ecs_world: Any
    actor_bots: dict[str, Bot]
    sensor_update_system: Any
    profiler: BotLoopProfiler
    terrain: Any
    engine_adapter: Any


def update_bot_steps(
    timers: LoopTimers,
    *,
    context: BotLoopContext,
) -> dict[str, ControlTuple | None]:
    bot_controls_by_uid: dict[str, ControlTuple | None] = {}
    bot_dt = timers.bot_dt
    profiler = context.profiler
    while timers.should_step_bot():
        timers.consume_bot()
        if context.actor_bots:
            context.sensor_update_system.update(bot_dt)
            for uid, bot in list(context.actor_bots.items()):
                actor = context.ecs_world.get_entity_by_id(uid)
                if actor is None:
                    continue
                ls = actor.get_component(LanderState)
                if ls is None or ls.state not in ("flying", "landed"):
                    continue
                current_bot = context.actor_bots.get(uid, bot)
                profiler.record_tick(uid)

                t0 = perf_counter() if profiler.enabled else 0.0
                passive_sensors = build_passive_sensors(actor, context.terrain)
                if profiler.enabled:
                    profiler.record_passive_build(uid, perf_counter() - t0)

                if isinstance(current_bot, QueryBot):
                    update_s = 0.0
                    t_plan = perf_counter() if profiler.enabled else 0.0
                    raw_queries = current_bot.plan(bot_dt, passive_sensors)
                    queries = list(raw_queries or [])
                    if profiler.enabled:
                        update_s += perf_counter() - t_plan

                    t_eval = perf_counter() if profiler.enabled else 0.0
                    query_results, batch_stats = evaluate_bot_queries(
                        actor,
                        context.engine_adapter,
                        context.terrain,
                        queries,
                    )
                    if profiler.enabled:
                        profiler.record_query_eval(
                            uid,
                            perf_counter() - t_eval,
                            query_total=batch_stats.total,
                            query_raycast=batch_stats.raycast,
                            query_terrain_profile=batch_stats.terrain_profile,
                            query_ballistic=batch_stats.ballistic,
                        )

                    t_act = perf_counter() if profiler.enabled else 0.0
                    action: BotAction = current_bot.act(
                        bot_dt,
                        passive_sensors,
                        query_results,
                    )
                    if profiler.enabled:
                        update_s += perf_counter() - t_act
                        profiler.record_bot_update(uid, update_s)
                else:
                    t_active = perf_counter() if profiler.enabled else 0.0
                    active_sensors = build_active_sensors(
                        actor,
                        context.engine_adapter,
                        context.terrain,
                    )
                    if profiler.enabled:
                        profiler.record_active_build(uid, perf_counter() - t_active)

                    t_update = perf_counter() if profiler.enabled else 0.0
                    action = current_bot.update(
                        bot_dt,
                        passive_sensors,
                        active_sensors,
                    )
                    if profiler.enabled:
                        profiler.record_bot_update(uid, perf_counter() - t_update)
                bot_controls_by_uid[uid] = (
                    action.target_thrust,
                    action.target_angle,
                    action.refuel,
                )
    return bot_controls_by_uid
