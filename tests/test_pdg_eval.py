from __future__ import annotations

from bots.pdg.config import PDGConfig
from bots.pdg.eval import build_evaluation_decision, reset_evaluation_state


class _Bot:
    def __init__(self, *, eval_goal: str = "landing", setup_done: bool = False) -> None:
        self._eval_goal = eval_goal
        self._cfg = PDGConfig()
        self._setup_gate_done = setup_done
        self._setup_gate_time = 6.0
        self._setup_gate_altitude = 120.0
        self._setup_gate_projected_dx = 9.0
        self._last_flight_snapshot = {"kind": "pdg"}
        self._elapsed_time_s = 99.0
        self._active_phase = "flare"
        self._setup_gate_projected_apex_y = 1.0
        self._setup_gate_projected_apex_over_target = 72.0
        self._setup_gate_has_target_y_solution = True
        self._setup_gate_projected_impact_angle_deg = 55.0
        self._setup_burn_started = True
        self._setup_burn_start_time = 1.0
        self._setup_burn_idle_since = 1.0
        self._setup_cut_latched = False
        self._setup_settle_start_time = None
        self._setup_quality_verdict = None
        self._setup_gate_quality_pass = None
        self._setup_gate_quality_verdict = None
        self._flare_entry_done = True
        self._flare_entry_time = 7.0
        self._flare_entry_altitude = 80.0
        self._flare_entry_projected_dx = 4.0
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
        self._shape_anchor_dx_abs = 400.0
        self._last_target_half = 55.0
        self.shape_reset_calls = 0

    def get_eval_goal(self) -> str:
        return self._eval_goal

    def _shape_apex_target(self, dx_abs: float) -> float:
        return max(
            self._cfg.setup_apex_height_min,
            min(self._cfg.setup_apex_height_max, self._cfg.setup_apex_height_per_dx * dx_abs),
        )

    def _reset_shape_window_state(self) -> None:
        self.shape_reset_calls += 1


def test_build_evaluation_decision_returns_setup_goal_completion() -> None:
    decision = build_evaluation_decision(_Bot(eval_goal="setup", setup_done=True))

    assert decision is not None
    assert decision.should_end is True
    assert decision.success is True
    assert decision.failure_mode == "none"
    assert decision.end_reason == "goal_reached"
    assert decision.metrics == {"setup_quality_verdict": "pass", "setup_quality_pass": True}


def test_build_evaluation_decision_returns_setup_quality_failure() -> None:
    bot = _Bot(eval_goal="setup", setup_done=True)
    bot._setup_gate_projected_dx = 120.0

    decision = build_evaluation_decision(bot)

    assert decision is not None
    assert decision.should_end is True
    assert decision.success is False
    assert decision.failure_mode == "setup_quality_failed"
    assert decision.end_reason == "setup_quality_failed"
    assert decision.metrics == {"setup_quality_verdict": "dx"}


def test_build_evaluation_decision_allows_steep_downhill_setup_entry() -> None:
    bot = _Bot(eval_goal="setup", setup_done=True)
    bot._setup_gate_y = 120.0
    bot._last_target_y = 0.0
    bot._setup_gate_projected_apex_over_target = 192.0
    bot._setup_gate_projected_impact_angle_deg = 78.0

    decision = build_evaluation_decision(bot)

    assert decision is not None
    assert decision.success is True
    assert decision.metrics == {"setup_quality_verdict": "pass", "setup_quality_pass": True}


def test_build_evaluation_decision_ignores_other_goals_or_missing_setup_gate() -> None:
    assert build_evaluation_decision(_Bot(eval_goal="landing", setup_done=True)) is None
    assert build_evaluation_decision(_Bot(eval_goal="setup", setup_done=False)) is None


def test_reset_evaluation_state_preserves_or_clears_last_snapshot() -> None:
    bot = _Bot(eval_goal="setup", setup_done=True)

    reset_evaluation_state(bot)
    assert bot._last_flight_snapshot == {"kind": "pdg"}
    assert bot._elapsed_time_s == 0.0
    assert bot._active_phase == "setup"
    assert bot._setup_gate_done is False
    assert bot._flare_entry_done is False
    assert bot._setup_cut_latched is False
    assert bot._setup_burn_start_time is None
    assert bot._setup_settle_start_time is None
    assert bot._setup_gate_quality_pass is None
    assert bot._setup_gate_quality_verdict is None
    assert bot._clearance_active is False
    assert bot._debug_setup_last_print_t == -1.0
    assert bot._debug_setup_post_end_time is None
    assert bot.shape_reset_calls == 1

    reset_evaluation_state(bot, clear_last_flight_snapshot=True)
    assert bot._last_flight_snapshot is None
    assert bot.shape_reset_calls == 2
