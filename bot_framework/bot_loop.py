from __future__ import annotations

from time import perf_counter
from typing import Protocol, runtime_checkable, Any

from core.bot import BotAction
from core.components import LanderState

from core.control_types import ControlTuple


@runtime_checkable
class LoopTimersLike(Protocol):
    bot_dt: float
    elapsed_time: float

    def should_step_bot(self) -> bool: ...

    def consume_bot(self) -> None: ...


@runtime_checkable
class BotLoopContextLike(Protocol):
    profiler: Any
    actor_bots: dict[str, Any]
    ecs_world: Any
    sensor_update_system: Any
    terrain: Any
    trace_recorder: Any
    build_sensors: Any


def update_bot_steps(
    timers: LoopTimersLike,
    *,
    context: BotLoopContextLike,
) -> dict[str, ControlTuple | None]:
    bot_controls_by_uid: dict[str, ControlTuple | None] = {}
    bot_dt = timers.bot_dt
    profiler = context.profiler
    build_sensors = context.build_sensors
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

                passive_s = 0.0
                update_s = 0.0

                t0 = perf_counter() if profiler.enabled else 0.0
                sensors = build_sensors(actor, context.terrain)
                if profiler.enabled:
                    passive_s = perf_counter() - t0
                    profiler.record_passive_build(uid, passive_s)

                t_update = perf_counter() if profiler.enabled else 0.0
                action: BotAction = current_bot.update(bot_dt, sensors)
                if profiler.enabled:
                    update_s = perf_counter() - t_update
                    profiler.record_bot_update(uid, update_s)
                if profiler.enabled:
                    profiler.record_tick_costs(
                        uid,
                        passive_s=passive_s,
                        update_s=update_s,
                    )
                if context.trace_recorder is not None:
                    record_bot_action = getattr(
                        context.trace_recorder, "record_bot_action", None
                    )
                    if callable(record_bot_action):
                        record_bot_action(
                            uid=uid,
                            elapsed_time_s=timers.elapsed_time,
                            bot_dt_s=bot_dt,
                            sensors=sensors,
                            action=action,
                            passive_s=passive_s,
                            update_s=update_s,
                            bot=current_bot,
                        )
                bot_controls_by_uid[uid] = (
                    action.target_thrust,
                    action.target_angle,
                    action.refuel,
                )
    return bot_controls_by_uid
