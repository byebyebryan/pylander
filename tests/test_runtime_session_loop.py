from __future__ import annotations

from game.core.bot import BotEvalDecision
from game.core.components import FlightState, LanderState, Transform
from game.core.ecs import Entity
from game.runtime.loop_timing import LoopTimers
from bot_framework.bot_profiler import BotLoopProfiler
from game.runtime.session_loop import (
    SessionLoopContext,
    capture_actor_states,
    merge_controls,
    run_session_loop,
    sync_landed_to_flying_engine_state,
    update_bot_override_timer,
)


def test_update_bot_override_timer_resets_and_decays() -> None:
    assert (
        update_bot_override_timer(
            current_timer=0.2,
            override_delay=1.0,
            frame_dt=0.1,
            user_controls=(0.5, 0.0, False),
        )
        == 1.0
    )
    assert (
        update_bot_override_timer(
            current_timer=0.2,
            override_delay=1.0,
            frame_dt=0.1,
            user_controls=None,
        )
        == 0.1
    )


def test_merge_controls_keeps_active_user_override_only() -> None:
    controls = merge_controls(
        active_uid="player",
        user_controls=(0.6, 0.1, False),
        bot_controls={
            "player": (0.2, 0.0, False),
            "wingman": (0.4, -0.1, False),
        },
        bot_override_timer=0.0,
    )

    assert controls["player"] == (0.6, 0.1, False)
    assert controls["wingman"] == (0.4, -0.1, False)


def test_capture_actor_states_and_sync_landed_to_flying_engine_state() -> None:
    actor = Entity("lander")
    actor.add_component(LanderState(state="landed"))
    actor.add_component(Transform())

    class _StubEngine:
        def __init__(self) -> None:
            self.teleports: list[tuple[str, bool]] = []

        def teleport(
            self, _pos, *, angle: float, clear_velocity: bool, uid: str
        ) -> None:
            _ = angle
            self.teleports.append((uid, clear_velocity))

    state_before = capture_actor_states([actor])
    actor.get_component(LanderState).state = FlightState.FLYING  # type: ignore[union-attr]
    engine = _StubEngine()

    sync_landed_to_flying_engine_state(
        actors=[actor],
        engine=engine,
        state_before=state_before,
    )

    assert engine.teleports == [("lander", True)]


def test_run_session_loop_stops_on_bot_eval_before_level_end() -> None:
    calls: list[str] = []
    actor = Entity("lander")
    actor.add_component(LanderState(state="flying"))

    class _ControlRouting:
        def set_controls_map(self, _controls) -> None:
            calls.append("set_controls")

        def update(self, _dt: float) -> None:
            calls.append("control_routing")

    class _System:
        def __init__(self, name: str) -> None:
            self.name = name

        def update(self, _dt: float) -> None:
            calls.append(self.name)

    class _StubSystemsBundle:
        def __init__(self) -> None:
            self.control_routing = _ControlRouting()
            self.refuel = _System("refuel")
            self.state_transition = _System("state_transition")
            self.sensor_update = _System("sensor_update")

    class _Metrics:
        def update_for_actor(self, _actor, *, dt_used: float) -> None:
            calls.append(f"metrics_dt:{dt_used:.3f}")

        def update_state_counters(self, _actor, *, elapsed_time: float) -> None:
            calls.append(f"metrics_state:{elapsed_time:.3f}")

    class _TraceRecorder:
        def update(self, _dt: float, *, elapsed_time_s: float) -> None:
            _ = elapsed_time_s
            calls.append("trace_recorder")

        def record_controls_map(
            self, *, elapsed_time_s: float, controls_by_uid
        ) -> None:
            _ = elapsed_time_s, controls_by_uid
            calls.append("record_controls")

        def record_eval_decision(self, *, elapsed_time_s: float, decision) -> None:
            _ = elapsed_time_s, decision
            calls.append("record_eval_decision")

    context = SessionLoopContext(
        headless=True,
        actors=[actor],
        engine=type("_Engine", (), {"enabled": False})(),
        systems=_StubSystemsBundle(),
        trace_recorder=_TraceRecorder(),
        bot_profiler=BotLoopProfiler(enabled=False),
        metrics=_Metrics(),  # type: ignore[arg-type]
        bot_override_delay=1.0,
        bot_override_timer=0.0,
        is_running=lambda: True,
        active_uid=lambda: "lander",
        get_active_actor=lambda: actor,
        process_input=lambda _dt: (None, {}),
        set_elapsed_time=lambda _elapsed: calls.append("set_elapsed"),
        update_physics_steps=lambda _timers: calls.append("physics"),
        update_bot_steps=lambda _timers: {"lander": (0.4, 0.0, False)},
        level_update=lambda _dt: calls.append("level_update"),
        track_plot_events=lambda: calls.append("plot_events"),
        render=lambda _dt: 1.0 / 60.0,
        print_headless_stats=lambda _timers: calls.append("print_stats"),
        resolve_headless_bot_eval_decision=lambda: BotEvalDecision(
            should_end=True,
            success=True,
            end_reason="goal_reached",
        ),
        level_should_end=lambda: calls.append("level_should_end") or False,
    )

    result = run_session_loop(
        context=context,
        timers=LoopTimers(
            physics_dt=1.0 / 60.0, bot_dt=1.0 / 20.0, frame_dt=1.0 / 60.0
        ),
        print_freq=0,
        max_time=10.0,
        max_steps=10,
    )

    assert result.bot_eval_decision == BotEvalDecision(
        should_end=True,
        success=True,
        end_reason="goal_reached",
    )
    assert "level_should_end" not in calls
    assert calls[:9] == [
        "set_elapsed",
        "physics",
        "set_controls",
        "record_controls",
        "control_routing",
        "refuel",
        "state_transition",
        "sensor_update",
        "level_update",
    ]
    assert "record_eval_decision" in calls
