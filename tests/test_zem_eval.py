from __future__ import annotations

from bots._zem_eval import build_evaluation_decision, reset_evaluation_state


class _Bot:
    def __init__(self, *, eval_goal: str = "landing", setup_done: bool = False) -> None:
        self._eval_goal = eval_goal
        self._setup_gate_done = setup_done
        self._setup_gate_time = 6.0
        self._setup_gate_altitude = 120.0
        self._setup_gate_projected_dx = 9.0
        self._last_flight_snapshot = {"kind": "zem_zev"}
        self._elapsed_time_s = 99.0
        self._active_phase = "terminal"
        self._setup_gate_projected_apex_y = 1.0
        self._setup_gate_projected_apex_over_target = 2.0
        self._setup_burn_started = True
        self._setup_burn_idle_since = 1.0
        self._terminal_gate_done = True
        self._terminal_gate_time = 7.0
        self._terminal_gate_altitude = 80.0
        self._terminal_gate_projected_dx = 4.0
        self._last_projection_dx = 3.0
        self._last_projection_t_fall = 2.0
        self._last_projection_has_target_y = True
        self._last_target_y = 5.0
        self._peak_alt_over_target = 8.0
        self._lateral_overshoot = 1.0
        self._hover_time = 2.0
        self._clearance_margin = 3.0
        self._clearance_scale = 4.0
        self._clearance_active = True
        self._uphill_transfer = True
        self._debug_setup_last_print_t = 5.0
        self._debug_setup_post_end_time = 6.0
        self.shape_reset_calls = 0

    def get_eval_goal(self) -> str:
        return self._eval_goal

    def _reset_shape_window_state(self) -> None:
        self.shape_reset_calls += 1


def test_build_evaluation_decision_returns_setup_goal_completion() -> None:
    decision = build_evaluation_decision(_Bot(eval_goal="setup", setup_done=True))

    assert decision is not None
    assert decision.should_end is True
    assert decision.success is True
    assert decision.failure_mode == "none"
    assert decision.end_reason == "goal_reached"
    assert decision.metrics == {
        "zem_goal_setup_done": True,
        "zem_goal_setup_time": 6.0,
        "zem_goal_setup_altitude": 120.0,
        "zem_goal_setup_projected_dx": 9.0,
    }


def test_build_evaluation_decision_ignores_other_goals_or_missing_setup_gate() -> None:
    assert build_evaluation_decision(_Bot(eval_goal="landing", setup_done=True)) is None
    assert build_evaluation_decision(_Bot(eval_goal="setup", setup_done=False)) is None


def test_reset_evaluation_state_preserves_or_clears_last_snapshot() -> None:
    bot = _Bot(eval_goal="setup", setup_done=True)

    reset_evaluation_state(bot)
    assert bot._last_flight_snapshot == {"kind": "zem_zev"}
    assert bot._elapsed_time_s == 0.0
    assert bot._active_phase == "setup"
    assert bot._setup_gate_done is False
    assert bot._terminal_gate_done is False
    assert bot._clearance_active is False
    assert bot._debug_setup_last_print_t == -1.0
    assert bot._debug_setup_post_end_time is None
    assert bot.shape_reset_calls == 1

    reset_evaluation_state(bot, clear_last_flight_snapshot=True)
    assert bot._last_flight_snapshot is None
    assert bot.shape_reset_calls == 2
