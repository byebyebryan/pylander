from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from core.bot import BotEvalDecision
from core.components import LanderState, Transform
from core.ecs import Entity

if TYPE_CHECKING:
    from core.physics import PhysicsEngine
from runtime.loop_timing import LoopTimers
from runtime.metrics import BotLoopProfiler, RunMetricsTracker
from core.control_types import ControlTuple


def update_bot_override_timer(
    *,
    current_timer: float,
    override_delay: float,
    frame_dt: float,
    user_controls: ControlTuple | None,
) -> float:
    if user_controls is not None:
        return float(override_delay)
    return max(0.0, float(current_timer) - float(frame_dt))


def merge_controls(
    *,
    active_uid: str,
    user_controls: ControlTuple | None,
    bot_controls: dict[str, ControlTuple | None],
    bot_override_timer: float,
) -> dict[str, ControlTuple | None]:
    controls_by_uid: dict[str, ControlTuple | None] = {}
    if user_controls is not None:
        controls_by_uid[active_uid] = user_controls
    if bot_override_timer != 0.0:
        return controls_by_uid
    for uid, controls in bot_controls.items():
        if uid == active_uid and user_controls is not None:
            continue
        controls_by_uid[uid] = controls
    return controls_by_uid


def capture_actor_states(actors: list[Entity]) -> dict[str, str]:
    state_before: dict[str, str] = {}
    for actor in actors:
        ls = actor.get_component(LanderState)
        if ls is not None:
            state_before[actor.uid] = ls.state
    return state_before


def sync_landed_to_flying_engine_state(
    *,
    actors: list[Entity],
    engine: PhysicsEngine,
    state_before: dict[str, str],
) -> None:
    for actor in actors:
        before = state_before.get(actor.uid)
        ls = actor.get_component(LanderState)
        trans = actor.get_component(Transform)
        if before != "landed" or ls is None or trans is None:
            continue
        if ls.state == "flying":
            engine.teleport(
                trans.pos,
                angle=trans.rotation,
                clear_velocity=True,
                uid=actor.uid,
            )


@dataclass
class SessionLoopContext:
    headless: bool
    actors: list[Entity]
    engine: PhysicsEngine
    control_routing_system: Any
    refuel_system: Any
    state_transition_system: Any
    sensor_update_system: Any
    trace_recorder: Any
    bot_profiler: BotLoopProfiler
    metrics: RunMetricsTracker
    bot_override_delay: float
    bot_override_timer: float
    is_running: Callable[[], bool]
    active_uid: Callable[[], str]
    get_active_actor: Callable[[], Entity]
    process_input: Callable[[float], tuple[ControlTuple | None, dict]]
    set_elapsed_time: Callable[[float], None]
    update_physics_steps: Callable[[LoopTimers], None]
    update_bot_steps: Callable[[LoopTimers], dict[str, ControlTuple | None]]
    level_update: Callable[[float], None]
    track_plot_events: Callable[[], None]
    render: Callable[[float], float]
    print_headless_stats: Callable[[LoopTimers], None]
    resolve_headless_bot_eval_decision: Callable[[], BotEvalDecision | None]
    level_should_end: Callable[[], bool]


@dataclass
class SessionLoopResult:
    timers: LoopTimers
    metrics: RunMetricsTracker
    bot_eval_decision: BotEvalDecision | None
    bot_override_timer: float


def run_session_loop(
    *,
    context: SessionLoopContext,
    timers: LoopTimers,
    print_freq: int,
    max_time: float | None,
    max_steps: int | None,
) -> SessionLoopResult:
    step_count = 0
    frame_dt = timers.frame_dt
    bot_eval_decision: BotEvalDecision | None = None

    while context.is_running():
        if (
            context.headless
            and max_time is not None
            and timers.elapsed_time >= max_time
        ):
            break
        if max_steps is not None and step_count >= max_steps:
            break

        user_controls, _ = context.process_input(frame_dt)
        if not context.is_running():
            break

        timers.advance_frame(frame_dt)
        context.set_elapsed_time(timers.elapsed_time)

        context.update_physics_steps(timers)
        bot_controls = context.update_bot_steps(timers)
        if context.bot_profiler.enabled:
            for line in context.bot_profiler.maybe_report_lines(timers.elapsed_time):
                print(line)

        context.bot_override_timer = update_bot_override_timer(
            current_timer=context.bot_override_timer,
            override_delay=context.bot_override_delay,
            frame_dt=frame_dt,
            user_controls=user_controls,
        )
        controls_by_uid = merge_controls(
            active_uid=context.active_uid(),
            user_controls=user_controls,
            bot_controls=bot_controls,
            bot_override_timer=context.bot_override_timer,
        )

        state_before = capture_actor_states(context.actors)

        context.control_routing_system.set_controls_map(controls_by_uid)
        record_controls_map = getattr(
            context.trace_recorder, "record_controls_map", None
        )
        if callable(record_controls_map):
            record_controls_map(
                elapsed_time_s=timers.elapsed_time,
                controls_by_uid=controls_by_uid,
            )
        context.control_routing_system.update(frame_dt)
        context.refuel_system.update(frame_dt)
        context.state_transition_system.update(frame_dt)
        sync_landed_to_flying_engine_state(
            actors=context.actors,
            engine=context.engine,
            state_before=state_before,
        )

        context.sensor_update_system.update(frame_dt)
        context.level_update(frame_dt)
        context.track_plot_events()
        context.trace_recorder.update(frame_dt, elapsed_time_s=timers.elapsed_time)
        frame_dt = context.render(frame_dt)
        step_count += 1

        if context.headless and print_freq > 0 and step_count % print_freq == 0:
            context.print_headless_stats(timers)

        active_actor = context.get_active_actor()
        context.metrics.update_for_actor(
            active_actor, dt_used=max(0.0, float(frame_dt))
        )
        context.metrics.update_state_counters(
            active_actor, elapsed_time=timers.elapsed_time
        )

        decision = context.resolve_headless_bot_eval_decision()
        if decision is not None and decision.should_end:
            record_eval_decision = getattr(
                context.trace_recorder, "record_eval_decision", None
            )
            if callable(record_eval_decision):
                record_eval_decision(
                    elapsed_time_s=timers.elapsed_time,
                    decision=decision,
                )
            bot_eval_decision = decision
            break

        if context.level_should_end():
            break

    return SessionLoopResult(
        timers=timers,
        metrics=context.metrics,
        bot_eval_decision=bot_eval_decision,
        bot_override_timer=context.bot_override_timer,
    )
