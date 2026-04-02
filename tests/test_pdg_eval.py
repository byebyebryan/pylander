from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from bots.pdg_config import PDGConfig

from bots.pdg_eval import (
    build_evaluation_decision,
    build_evaluation_snapshot,
    reset_evaluation_state,
)


class _Bot:
    def __init__(self, *, eval_goal: str = "landing", boost_done: bool = False) -> None:
        self._eval_goal = eval_goal
        self._cfg = PDGConfig()
        self._boost_cutoff_done = boost_done
        self._boost_cutoff_time = 6.0
        self._boost_cutoff_altitude = 120.0
        self._boost_cutoff_projected_dx = 9.0
        self._last_flight_snapshot = {"kind": "pdg"}
        self._elapsed_time_s = 99.0
        self._active_phase = "terminal"
        self._boost_cutoff_projected_apex_y = 1.0
        self._boost_cutoff_projected_apex_over_target = 72.0
        self._boost_cutoff_has_target_y_solution = True
        self._boost_cutoff_projected_impact_angle_deg = 55.0
        self._boost_cutoff_y = 120.0
        self._boost_burn_started = True
        self._boost_burn_start_time = 1.0
        self._boost_burn_idle_since = 1.0
        self._boost_cut_latched = False
        self._boost_settle_start_time = None
        self._boost_quality_verdict: str | None = None
        self._boost_cutoff_quality_pass: bool | None = None
        self._boost_cutoff_quality_verdict: str | None = None
        self._terminal_entry_done = True
        self._terminal_entry_time = 7.0
        self._terminal_entry_altitude = 80.0
        self._terminal_entry_projected_dx = 4.0
        self._terminal_post_entry_apex_gain = 18.0
        self._terminal_post_entry_time_to_apex = 1.5
        self._terminal_post_entry_peak_abs_dx = 26.0
        self._solve_count = 3
        self._solve_ms_sum = 12.0
        self._solve_ms_samples = [2.0, 4.0, 6.0]
        self._terminal_probe_count = 2
        self._terminal_probe_ms_sum = 5.0
        self._terminal_probe_ms_samples = [2.0, 3.0]
        self._terminal_gate_mode = "latest_safe"
        self._terminal_gate_horizon_s = 14.0
        self._terminal_gate_terminal_speed = None
        self._terminal_gate_peak_accel_ratio = None
        self._terminal_gate_od_excess_s = None
        self._terminal_gate_latest_safe_margin_s = -0.25
        self._terminal_gate_required_accel_ratio = 0.5
        self._terrain_divert_mode = "lateral_containment"
        self._terrain_divert_margin_min = -3.5
        self._terrain_divert_first_limit_t = 1.25
        self._terrain_divert_worst_x = 242.0
        self._terrain_divert_horizon_s = 3.0
        self._terrain_divert_sample_count = 10
        self._fallback_frames = 1
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
        self._debug_boost_last_print_t = 5.0
        self._debug_boost_post_end_time = 6.0
        self._shape_anchor_dx_abs = 400.0
        self._shape_apex_actual_over_target = 24.0
        self._shape_apex_target_over_target = 20.0
        self._shape_projected_dx_abs_max = 18.0
        self._shape_projected_dx_count = 2
        self._state: Any = None
        self._last_target_half = 55.0
        self.shape_reset_calls = 0

        self._state = SimpleNamespace(
            _elapsed_time_s=self._elapsed_time_s,
            _active_phase=self._active_phase,
            _active_stage=None,
            _boost_cutoff_done=self._boost_cutoff_done,
            _boost_cutoff_time=self._boost_cutoff_time,
            _boost_cutoff_altitude=self._boost_cutoff_altitude,
            _boost_cutoff_projected_dx=self._boost_cutoff_projected_dx,
            _boost_cutoff_projected_apex_y=self._boost_cutoff_projected_apex_y,
            _boost_cutoff_projected_apex_over_target=self._boost_cutoff_projected_apex_over_target,
            _boost_cutoff_has_target_y_solution=self._boost_cutoff_has_target_y_solution,
            _boost_cutoff_projected_impact_dx=None,
            _boost_cutoff_projected_impact_angle_deg=self._boost_cutoff_projected_impact_angle_deg,
            _boost_cutoff_burn_duration_s=None,
            _boost_cutoff_burn_fuel_used=None,
            _boost_cutoff_burn_avg_thrust_level=None,
            _boost_cutoff_x=None,
            _boost_cutoff_y=self._boost_cutoff_y,
            _boost_cutoff_vx=None,
            _boost_cutoff_vy_up=None,
            _boost_cutoff_spawn_primed=False,
            _boost_phase_thrust_integral=0.0,
            _boost_phase_fuel_start=None,
            _boost_burn_started=self._boost_burn_started,
            _boost_burn_start_time=self._boost_burn_start_time,
            _boost_burn_idle_since=self._boost_burn_idle_since,
            _boost_cut_latched=self._boost_cut_latched,
            _boost_cut_hold_angle=None,
            _boost_settle_start_time=self._boost_settle_start_time,
            _boost_quality_verdict=self._boost_quality_verdict,
            _boost_cutoff_quality_pass=self._boost_cutoff_quality_pass,
            _boost_cutoff_quality_verdict=self._boost_cutoff_quality_verdict,
            _terminal_entry_done=self._terminal_entry_done,
            _terminal_entry_time=self._terminal_entry_time,
            _terminal_entry_altitude=self._terminal_entry_altitude,
            _terminal_entry_projected_dx=self._terminal_entry_projected_dx,
            _terminal_entry_x=None,
            _terminal_entry_y=None,
            _terminal_post_entry_apex_gain=self._terminal_post_entry_apex_gain,
            _terminal_post_entry_time_to_apex=self._terminal_post_entry_time_to_apex,
            _terminal_post_entry_peak_abs_dx=self._terminal_post_entry_peak_abs_dx,
            _terminal_gate_ready_ticks=0,
            _terminal_probe_count=self._terminal_probe_count,
            _terminal_probe_ms_sum=self._terminal_probe_ms_sum,
            _terminal_probe_ms_samples=list(self._terminal_probe_ms_samples),
            _terminal_gate_mode=self._terminal_gate_mode,
            _terminal_gate_horizon_s=self._terminal_gate_horizon_s,
            _terminal_gate_terminal_speed=self._terminal_gate_terminal_speed,
            _terminal_gate_peak_accel_ratio=self._terminal_gate_peak_accel_ratio,
            _terminal_gate_od_excess_s=self._terminal_gate_od_excess_s,
            _terminal_gate_latest_safe_margin_s=self._terminal_gate_latest_safe_margin_s,
            _terminal_gate_required_accel_ratio=self._terminal_gate_required_accel_ratio,
            _terrain_divert_mode=self._terrain_divert_mode,
            _terrain_divert_margin_min=self._terrain_divert_margin_min,
            _terrain_divert_first_limit_t=self._terrain_divert_first_limit_t,
            _terrain_divert_worst_x=self._terrain_divert_worst_x,
            _terrain_divert_worst_y=None,
            _terrain_divert_horizon_s=self._terrain_divert_horizon_s,
            _terrain_divert_sample_count=self._terrain_divert_sample_count,
            _last_projection_dx=self._last_projection_dx,
            _last_projection_t_fall=self._last_projection_t_fall,
            _last_projection_has_target_y=self._last_projection_has_target_y,
            _last_target_y=self._last_target_y,
            _peak_alt_over_target=self._peak_alt_over_target,
            _lateral_overshoot=self._lateral_overshoot,
            _hover_time=self._hover_time,
            _clearance_margin=self._clearance_margin,
            _clearance_scale=self._clearance_scale,
            _clearance_active=self._clearance_active,
            _uphill_transfer=self._uphill_transfer,
            _debug_boost_last_print_t=self._debug_boost_last_print_t,
            _debug_boost_post_end_time=self._debug_boost_post_end_time,
            _shape_window_started=False,
            _shape_window_done=False,
            _shape_window_start_time=None,
            _shape_window_end_time=None,
            _shape_start_x=0.0,
            _shape_start_y=0.0,
            _shape_target_x=0.0,
            _shape_target_y=0.0,
            _shape_anchor_dx_abs=self._shape_anchor_dx_abs,
            _shape_apex_target_over_target=self._shape_apex_target_over_target,
            _shape_apex_actual_over_target=self._shape_apex_actual_over_target,
            _shape_curve_sq_err_sum=0.0,
            _shape_curve_count=0,
            _shape_projected_dx_abs_sum=0.0,
            _shape_projected_dx_abs_max=self._shape_projected_dx_abs_max,
            _shape_projected_dx_count=self._shape_projected_dx_count,
            _shape_shortfall_count=0,
            _shape_shortfall_sample_count=0,
        )

    @property
    def state(self) -> Any:
        return self._state

    def get_eval_goal(self) -> str:
        return self._eval_goal

    def _shape_apex_target(self, dx_abs: float) -> float:
        return max(
            self._cfg.boost_apex_height_min,
            min(
                self._cfg.boost_apex_height_max,
                self._cfg.boost_apex_height_per_dx * dx_abs,
            ),
        )

    def _shape_curve_rmse(self) -> float | None:
        return 3.5

    def _shape_projected_dx_abs_mean(self) -> float | None:
        return 11.0

    def _shape_shortfall_ratio(self) -> float | None:
        return 0.25

    def _reset_shape_window_state(self) -> None:
        self.shape_reset_calls += 1


def test_build_evaluation_decision_returns_boost_goal_completion() -> None:
    decision = build_evaluation_decision(
        _Bot(eval_goal="boost_cutoff", boost_done=True)
    )

    assert decision is not None
    assert decision.should_end is True
    assert decision.success is True
    assert decision.failure_mode == "none"
    assert decision.end_reason == "goal_reached"
    assert decision.metrics == {
        "boost_quality_verdict": "pass",
        "boost_quality_pass": True,
    }


def test_build_evaluation_decision_returns_boost_quality_failure() -> None:
    bot = _Bot(eval_goal="boost_cutoff", boost_done=True)
    bot.state._boost_cutoff_projected_dx = 120.0

    decision = build_evaluation_decision(bot)

    assert decision is not None
    assert decision.should_end is True
    assert decision.success is False
    assert decision.failure_mode == "boost_quality_failed"
    assert decision.end_reason == "boost_quality_failed"
    assert decision.metrics == {"boost_quality_verdict": "dx"}


def test_build_evaluation_decision_ignores_apex_mismatch_for_steep_boost_entry() -> (
    None
):
    bot = _Bot(eval_goal="boost_cutoff", boost_done=True)
    bot.state._boost_cutoff_y = 120.0
    bot.state._last_target_y = 0.0
    bot.state._boost_cutoff_projected_apex_over_target = 192.0
    bot.state._boost_cutoff_projected_impact_angle_deg = 78.0

    decision = build_evaluation_decision(bot)

    assert decision is not None
    assert decision.success is True
    assert decision.metrics == {
        "boost_quality_verdict": "pass",
        "boost_quality_pass": True,
    }


def test_build_evaluation_decision_ignores_other_goals_or_missing_boost_cutoff() -> (
    None
):
    assert build_evaluation_decision(_Bot(eval_goal="landing", boost_done=True)) is None
    assert (
        build_evaluation_decision(_Bot(eval_goal="boost_cutoff", boost_done=False))
        is None
    )


def test_reset_evaluation_state_preserves_or_clears_last_snapshot() -> None:
    bot = _Bot(eval_goal="boost_cutoff", boost_done=True)

    reset_evaluation_state(bot)
    assert bot._last_flight_snapshot == {"kind": "pdg"}
    assert bot.state._elapsed_time_s == 0.0
    assert bot.state._active_phase == "boost"
    assert bot.state._boost_cutoff_done is False
    assert bot.state._terminal_entry_done is False
    assert bot.state._terminal_post_entry_apex_gain is None
    assert bot.state._terminal_post_entry_time_to_apex is None
    assert bot.state._terminal_post_entry_peak_abs_dx is None
    assert bot.state._boost_cut_latched is False
    assert bot.state._boost_burn_start_time is None
    assert bot.state._boost_settle_start_time is None
    assert bot.state._boost_cutoff_quality_pass is None
    assert bot.state._boost_cutoff_quality_verdict is None
    assert bot.state._clearance_active is False
    assert bot.state._debug_boost_last_print_t == -1.0
    assert bot.state._debug_boost_post_end_time is None
    assert bot.shape_reset_calls == 1

    reset_evaluation_state(bot, clear_last_flight_snapshot=True)
    assert bot._last_flight_snapshot is None
    assert bot.shape_reset_calls == 2


def test_build_evaluation_snapshot_prefers_explicit_state_container() -> None:
    bot = _Bot(eval_goal="landing", boost_done=False)
    bot._shape_apex_actual_over_target = -999.0
    bot._shape_apex_target_over_target = -999.0
    bot._shape_projected_dx_abs_max = -1.0
    bot._shape_projected_dx_count = 0
    bot._terminal_entry_done = False
    bot._terminal_entry_time = -1.0
    bot._terminal_entry_projected_dx = -1.0
    bot._terminal_probe_count = 0
    bot._boost_cutoff_quality_verdict = "stale"
    bot._state = SimpleNamespace(
        _shape_apex_actual_over_target=28.0,
        _shape_apex_target_over_target=20.0,
        _shape_projected_dx_abs_max=42.0,
        _shape_projected_dx_count=3,
        _boost_cutoff_quality_verdict="pass",
        _boost_quality_verdict=None,
        _terminal_entry_done=True,
        _terminal_entry_time=9.0,
        _terminal_entry_altitude=70.0,
        _terminal_entry_projected_dx=3.25,
        _terminal_post_entry_apex_gain=22.0,
        _terminal_post_entry_time_to_apex=1.75,
        _terminal_post_entry_peak_abs_dx=18.0,
        _terminal_probe_count=4,
        _terminal_probe_ms_sum=14.0,
        _terminal_probe_ms_samples=[2.0, 3.0, 4.0, 5.0],
        _terminal_gate_mode="nominal_ready",
        _terminal_gate_horizon_s=12.0,
        _terminal_gate_terminal_speed=None,
        _terminal_gate_peak_accel_ratio=None,
        _terminal_gate_od_excess_s=None,
        _terminal_gate_latest_safe_margin_s=0.4,
        _terminal_gate_required_accel_ratio=0.33,
        _terrain_divert_mode="lateral_containment",
        _terrain_divert_margin_min=-2.5,
        _terrain_divert_first_limit_t=0.75,
        _terrain_divert_worst_x=236.0,
        _terrain_divert_worst_y=None,
        _terrain_divert_horizon_s=3.5,
        _terrain_divert_sample_count=12,
    )

    snapshot = build_evaluation_snapshot(bot)

    assert snapshot["terminal_entry_done"] is True
    assert snapshot["terminal_entry_time"] == 9.0
    assert snapshot["terminal_entry_projected_dx"] == 3.25
    assert snapshot["terminal_post_entry_apex_gain"] == 22.0
    assert snapshot["terminal_post_entry_time_to_apex"] == 1.75
    assert snapshot["terminal_post_entry_peak_abs_dx"] == 18.0
    assert snapshot["terminal_probe_count"] == 4
    assert snapshot["terminal_gate_mode"] == "nominal_ready"
    assert snapshot["terrain_divert_mode"] == "lateral_containment"
    assert snapshot["terrain_divert_margin_min"] == -2.5
    assert snapshot["terrain_divert_first_limit_t"] == 0.75
    assert snapshot["terrain_divert_worst_x"] == 236.0
    assert snapshot["terrain_divert_sample_count"] == 12
    assert snapshot["boost_quality_verdict"] == "pass"
    assert snapshot["shape_apex_error"] == 8.0
    assert snapshot["shape_projected_dx_abs_max"] == 42.0


def test_build_evaluation_decision_prefers_explicit_boost_state_container() -> None:
    bot = _Bot(eval_goal="boost_cutoff", boost_done=False)
    bot._boost_cutoff_done = False
    bot._boost_cutoff_projected_dx = 999.0
    bot._state = SimpleNamespace(
        _boost_cutoff_done=True,
        _boost_cutoff_has_target_y_solution=True,
        _boost_cutoff_projected_dx=5.0,
        _boost_cutoff_projected_impact_angle_deg=70.0,
        _boost_cutoff_quality_pass=None,
        _boost_cutoff_quality_verdict=None,
    )

    decision = build_evaluation_decision(bot)

    assert decision is not None
    assert decision.success is True
    assert decision.metrics == {
        "boost_quality_verdict": "pass",
        "boost_quality_pass": True,
    }


def test_reset_evaluation_state_prefers_explicit_runtime_state_container() -> None:
    bot = _Bot(eval_goal="landing", boost_done=False)
    bot._state = SimpleNamespace(
        _elapsed_time_s=12.0,
        _active_phase="terminal",
        _active_stage="bad",
        _last_projection_dx=9.0,
        _last_projection_t_fall=4.0,
        _last_projection_has_target_y=True,
        _last_target_y=15.0,
        _peak_alt_over_target=22.0,
        _lateral_overshoot=3.0,
        _hover_time=4.0,
        _clearance_margin=5.0,
        _clearance_scale=6.0,
        _clearance_active=True,
        _uphill_transfer=True,
        _boost_cutoff_done=False,
        _boost_cutoff_time=None,
        _boost_cutoff_altitude=None,
        _boost_cutoff_projected_dx=None,
        _boost_cutoff_projected_apex_y=None,
        _boost_cutoff_projected_apex_over_target=None,
        _boost_cutoff_has_target_y_solution=None,
        _boost_cutoff_projected_impact_dx=None,
        _boost_cutoff_projected_impact_angle_deg=None,
        _boost_cutoff_burn_duration_s=None,
        _boost_cutoff_burn_fuel_used=None,
        _boost_cutoff_burn_avg_thrust_level=None,
        _boost_cutoff_x=None,
        _boost_cutoff_y=None,
        _boost_cutoff_vx=None,
        _boost_cutoff_vy_up=None,
        _boost_cutoff_spawn_primed=False,
        _boost_phase_thrust_integral=0.0,
        _boost_phase_fuel_start=None,
        _boost_burn_started=False,
        _boost_burn_start_time=None,
        _boost_burn_idle_since=None,
        _boost_cut_latched=False,
        _boost_cut_hold_angle=None,
        _boost_settle_start_time=None,
        _boost_quality_verdict=None,
        _boost_cutoff_quality_pass=None,
        _boost_cutoff_quality_verdict=None,
        _terminal_entry_done=False,
        _terminal_entry_time=None,
        _terminal_entry_altitude=None,
        _terminal_entry_projected_dx=None,
        _terminal_entry_x=None,
        _terminal_entry_y=None,
        _terminal_post_entry_apex_gain=None,
        _terminal_post_entry_time_to_apex=None,
        _terminal_post_entry_peak_abs_dx=None,
        _terminal_gate_ready_ticks=0,
        _terminal_probe_count=0,
        _terminal_probe_ms_sum=0.0,
        _terminal_probe_ms_samples=[],
        _terminal_gate_mode=None,
        _terminal_gate_horizon_s=None,
        _terminal_gate_terminal_speed=None,
        _terminal_gate_peak_accel_ratio=None,
        _terminal_gate_od_excess_s=None,
        _terminal_gate_latest_safe_margin_s=None,
        _terminal_gate_required_accel_ratio=None,
        _terrain_divert_mode=None,
        _terrain_divert_margin_min=None,
        _terrain_divert_first_limit_t=None,
        _terrain_divert_worst_x=None,
        _terrain_divert_worst_y=None,
        _terrain_divert_horizon_s=None,
        _terrain_divert_sample_count=0,
        _shape_apex_actual_over_target=0.0,
        _shape_apex_target_over_target=0.0,
        _shape_projected_dx_abs_max=0.0,
        _shape_projected_dx_count=0,
    )

    reset_evaluation_state(bot)

    assert bot.state._elapsed_time_s == 0.0
    assert bot.state._active_phase == "boost"
    assert bot.state._active_stage is None
    assert bot.state._last_projection_dx is None
    assert bot.state._last_projection_t_fall is None
    assert bot.state._last_projection_has_target_y is False
    assert bot.state._last_target_y == 0.0
    assert bot.state._peak_alt_over_target == 0.0
    assert bot.state._lateral_overshoot == 0.0
    assert bot.state._hover_time == 0.0
    assert bot.state._clearance_margin == 0.0
    assert bot.state._clearance_scale == 0.0
    assert bot.state._clearance_active is False
    assert bot.state._terminal_post_entry_apex_gain is None
    assert bot.state._terminal_post_entry_time_to_apex is None
    assert bot.state._terminal_post_entry_peak_abs_dx is None
