from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from game.core.bot import BotEvalDecision
from game.core.components import LanderState, Transform
from game.core.ecs import Entity

if TYPE_CHECKING:
    from game.core.physics import PhysicsEngine
    from game.runtime.bootstrap import SystemsBundle
from game.runtime.loop_timing import LoopTimers
from game.runtime.profiler import BotProfiler
from game.runtime.run_metrics import RunMetricsTracker
from game.core.control_types import ControlTuple


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


def _tick_systems(
    *,
    systems: SystemsBundle,
    trace_recorder: Any,
    actors: list[Entity],
    engine: PhysicsEngine,
    controls_by_uid: dict[str, Any],
    frame_dt: float,
    elapsed_time: float,
    level_update: Callable[[float], None],
) -> dict[str, str]:
    state_before = capture_actor_states(actors)

    systems.control_routing.set_controls_map(controls_by_uid)
    record_controls_map = getattr(trace_recorder, "record_controls_map", None)
    if callable(record_controls_map):
        record_controls_map(
            elapsed_time_s=elapsed_time,
            controls_by_uid=controls_by_uid,
        )
    systems.control_routing.update(frame_dt)
    systems.refuel.update(frame_dt)
    systems.state_transition.update(frame_dt)
    sync_landed_to_flying_engine_state(
        actors=actors,
        engine=engine,
        state_before=state_before,
    )

    systems.sensor_update.update(frame_dt)
    level_update(frame_dt)
    trace_recorder.update(frame_dt, elapsed_time_s=elapsed_time)

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
class SessionTickState:
    """Mutable state carried across session ticks."""

    step_count: int = 0
    frame_dt: float = 0.0
    bot_eval_decision: BotEvalDecision | None = None
    bot_override_timer: float = 0.0


@dataclass
class SessionTickResult:
    """Result of a single session tick."""

    running: bool = True
    elapsed_time: float = 0.0


@dataclass
class SessionLoopContext:
    headless: bool
    actors: list[Entity]
    engine: PhysicsEngine
    systems: SystemsBundle
    trace_recorder: Any
    bot_profiler: BotProfiler
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


def tick_session(
    *,
    context: SessionLoopContext,
    timers: LoopTimers,
    state: SessionTickState,
    print_freq: int = 0,
) -> SessionTickResult:
    """Execute one frame of simulation + rendering.

    Returns SessionTickResult with running=False if the session should end.
    """
    state.frame_dt = timers.frame_dt

    user_controls, _ = context.process_input(state.frame_dt)
    if not context.is_running():
        return SessionTickResult(running=False, elapsed_time=timers.elapsed_time)

    timers.advance_frame(state.frame_dt)
    context.set_elapsed_time(timers.elapsed_time)

    context.update_physics_steps(timers)
    bot_controls = context.update_bot_steps(timers)
    if context.bot_profiler.enabled:
        for line in context.bot_profiler.maybe_report_lines(timers.elapsed_time):
            print(line)

    state.bot_override_timer = update_bot_override_timer(
        current_timer=state.bot_override_timer,
        override_delay=context.bot_override_delay,
        frame_dt=state.frame_dt,
        user_controls=user_controls,
    )
    controls_by_uid = merge_controls(
        active_uid=context.active_uid(),
        user_controls=user_controls,
        bot_controls=bot_controls,
        bot_override_timer=state.bot_override_timer,
    )

    _tick_systems(
        systems=context.systems,
        trace_recorder=context.trace_recorder,
        actors=context.actors,
        engine=context.engine,
        controls_by_uid=controls_by_uid,
        frame_dt=state.frame_dt,
        elapsed_time=timers.elapsed_time,
        level_update=context.level_update,
    )
    context.track_plot_events()
    state.frame_dt = context.render(state.frame_dt)
    state.step_count += 1

    if context.headless and print_freq > 0 and state.step_count % print_freq == 0:
        context.print_headless_stats(timers)

    active_actor = context.get_active_actor()
    context.metrics.update_for_actor(
        active_actor, dt_used=max(0.0, float(state.frame_dt))
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
        state.bot_eval_decision = decision
        return SessionTickResult(running=False, elapsed_time=timers.elapsed_time)

    if context.level_should_end():
        return SessionTickResult(running=False, elapsed_time=timers.elapsed_time)

    return SessionTickResult(running=True, elapsed_time=timers.elapsed_time)


def run_session_loop(
    *,
    context: SessionLoopContext,
    timers: LoopTimers,
    print_freq: int,
    max_time: float | None,
    max_steps: int | None,
) -> SessionLoopResult:
    state = SessionTickState(
        frame_dt=timers.frame_dt,
        bot_override_timer=context.bot_override_timer,
    )

    while context.is_running():
        if (
            context.headless
            and max_time is not None
            and timers.elapsed_time >= max_time
        ):
            break
        if max_steps is not None and state.step_count >= max_steps:
            break

        result = tick_session(
            context=context,
            timers=timers,
            state=state,
            print_freq=print_freq,
        )

        if not result.running:
            break

    return SessionLoopResult(
        timers=timers,
        metrics=context.metrics,
        bot_eval_decision=state.bot_eval_decision,
        bot_override_timer=state.bot_override_timer,
    )


__all__ = [
    "SessionLoopContext",
    "SessionLoopResult",
    "SessionTickState",
    "SessionTickResult",
    "tick_session",
    "run_session_loop",
]
