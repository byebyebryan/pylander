"""Optimizer-first staged PDG bot.

This version uses a receding-horizon convex optimizer to generate coupled
horizontal/vertical thrust commands from a single objective each replan cycle.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, fields, replace
from typing import Any

from bots.common_ballistics import (
    BallisticProjection,
    estimate_target_y_projection,
)
from bots.common_math import clamp, engine_profile, finite_altitude, stable
from bots.common_targeting import pick_target, target_half_width
from bots.pdg_actuation import (
    command_from_plan as _command_from_plan_impl,
    command_passive_coast as _command_passive_coast_impl,
    command_zero_thrust_hold_angle as _command_zero_thrust_hold_angle_impl,
)
from bots.pdg_boost import (
    boost_cut_wind_down_s as _boost_cut_wind_down_s_impl,
    evaluate_boost_quality as _evaluate_boost_quality_impl,
    evaluate_boost_quality_after_settle as _evaluate_boost_quality_after_settle_impl,
    transfer_dy_for_boost as _transfer_dy_for_boost_impl,
)
from bots.pdg_config import PDGConfig
from bots.pdg_eval import (
    build_evaluation_decision as _build_evaluation_decision_impl,
    build_evaluation_snapshot as _build_evaluation_snapshot_impl,
    percentile as _percentile_impl,
    reset_evaluation_state as _reset_evaluation_state_impl,
    resolve_evaluation_snapshot as _resolve_evaluation_snapshot_impl,
)
from bots.pdg_optimizer import PDGOptimizer, PDGOptimizerConfig, PDGPlan
from bots.pdg_planner import solve_plan as _solve_plan_impl
from bots.pdg_stages import (
    BallisticCoastController,
    FlightStage,
    PDGBoostController,
    PDGTerminalController,
    StageController,
    StageTickResult,
    TakeoffBootstrapController,
    TouchdownBrakeController,
)
from bots.pdg_terminal_gate import (
    evaluate_terminal_gate as _evaluate_terminal_gate_impl,
)
from bots.pdg_tracking import (
    apply_boost_cutoff_metrics as _apply_boost_cutoff_metrics_impl,
    finalize_boost_cutoff_metrics as _finalize_boost_cutoff_metrics_impl,
    finalize_terminal_entry_metrics as _finalize_terminal_entry_metrics_impl,
    maybe_start_shape_window as _maybe_start_shape_window_impl,
    refresh_stage_tracking as _refresh_stage_tracking_impl,
    update_terminal_post_entry_metrics as _update_terminal_post_entry_metrics_impl,
    update_shape_window_metrics as _update_shape_window_metrics_impl,
)
from core.bot import (
    Bot,
    BotAction,
    BotDisplayState,
    BotEvalDecision,
    FlightPhaseSnapshot,
    PlotMarker,
    Sensors,
    BoostCutoffMetrics,
)
from core.config import GRAVITY
from core.eval_goals import EVAL_GOAL_BOOST_CUTOFF, EVAL_GOAL_LANDING

_GRAVITY_MAG = abs(float(GRAVITY))
_TERMINAL_OPT_PATH_X_WEIGHT = 0.030
_TERMINAL_OPT_PATH_Y_WEIGHT = 0.015
_TERMINAL_OPT_UPWARD_VY_WEIGHT = 1.20
_TERMINAL_OPT_ALTITUDE_PROGRESS_WEIGHT = 0.00


@dataclass(frozen=True)
class UpdateContext:
    dt: float
    passive: Sensors
    target: Any | None
    dx: float
    dy: float
    alt: float
    projection: BallisticProjection
    max_power: float
    min_throttle: float
    max_throttle: float
    ramp_up: float
    max_thrust_accel: float
    nominal_thrust_accel: float
    min_thrust_accel: float
    suggested_stage: FlightStage


@dataclass
class PDGState:
    _elapsed_time_s: float = 0.0
    _active_phase: str = "boost"
    _active_stage: FlightStage | None = None
    _boost_cutoff_done: bool = False
    _boost_cutoff_time: float | None = None
    _boost_cutoff_altitude: float | None = None
    _boost_cutoff_projected_dx: float | None = None
    _boost_cutoff_projected_apex_y: float | None = None
    _boost_cutoff_projected_apex_over_target: float | None = None
    _boost_cutoff_has_target_y_solution: bool | None = None
    _boost_cutoff_projected_impact_dx: float | None = None
    _boost_cutoff_projected_impact_angle_deg: float | None = None
    _boost_cutoff_burn_duration_s: float | None = None
    _boost_cutoff_burn_fuel_used: float | None = None
    _boost_cutoff_burn_avg_thrust_level: float | None = None
    _boost_cutoff_x: float | None = None
    _boost_cutoff_y: float | None = None
    _boost_cutoff_vx: float | None = None
    _boost_cutoff_vy_up: float | None = None
    _boost_cutoff_spawn_primed: bool = False
    _boost_phase_thrust_integral: float = 0.0
    _boost_phase_fuel_start: float | None = None
    _boost_burn_started: bool = False
    _boost_burn_start_time: float | None = None
    _boost_burn_idle_since: float | None = None
    _boost_cut_latched: bool = False
    _boost_cut_hold_angle: float | None = None
    _boost_settle_start_time: float | None = None
    _boost_quality_verdict: str | None = None
    _boost_cutoff_quality_pass: bool | None = None
    _boost_cutoff_quality_verdict: str | None = None
    _terminal_entry_done: bool = False
    _terminal_entry_time: float | None = None
    _terminal_entry_altitude: float | None = None
    _terminal_entry_projected_dx: float | None = None
    _terminal_entry_x: float | None = None
    _terminal_entry_y: float | None = None
    _terminal_post_entry_apex_gain: float | None = None
    _terminal_post_entry_time_to_apex: float | None = None
    _terminal_post_entry_peak_abs_dx: float | None = None
    _terminal_gate_ready_ticks: int = 0
    _terminal_probe_count: int = 0
    _terminal_probe_ms_sum: float = 0.0
    _terminal_probe_ms_samples: list[float] = field(default_factory=list)
    _terminal_gate_mode: str | None = None
    _terminal_gate_horizon_s: float | None = None
    _terminal_gate_terminal_speed: float | None = None
    _terminal_gate_peak_accel_ratio: float | None = None
    _terminal_gate_od_excess_s: float | None = None
    _terminal_gate_latest_safe_margin_s: float | None = None
    _terminal_gate_required_accel_ratio: float | None = None
    _terrain_divert_mode: str | None = None
    _terrain_divert_margin_min: float | None = None
    _terrain_divert_first_limit_t: float | None = None
    _terrain_divert_worst_x: float | None = None
    _terrain_divert_worst_y: float | None = None
    _terrain_divert_horizon_s: float | None = None
    _terrain_divert_sample_count: int = 0
    _last_projection_dx: float | None = None
    _last_projection_t_fall: float | None = None
    _last_projection_has_target_y: bool = False
    _last_target_y: float = 0.0
    _peak_alt_over_target: float = 0.0
    _lateral_overshoot: float = 0.0
    _hover_time: float = 0.0
    _clearance_margin: float = 0.0
    _clearance_scale: float = 0.0
    _clearance_active: bool = False
    _uphill_transfer: bool = False
    _debug_boost_last_print_t: float = -1.0
    _debug_boost_post_end_time: float | None = None
    _shape_window_started: bool = False
    _shape_window_done: bool = False
    _shape_window_start_time: float | None = None
    _shape_window_end_time: float | None = None
    _shape_start_x: float = 0.0
    _shape_start_y: float = 0.0
    _shape_target_x: float = 0.0
    _shape_target_y: float = 0.0
    _shape_anchor_dx_abs: float = 0.0
    _shape_apex_target_over_target: float = 0.0
    _shape_apex_actual_over_target: float = 0.0
    _shape_curve_sq_err_sum: float = 0.0
    _shape_curve_count: int = 0
    _shape_projected_dx_abs_sum: float = 0.0
    _shape_projected_dx_abs_max: float = 0.0
    _shape_projected_dx_count: int = 0
    _shape_shortfall_count: int = 0
    _shape_shortfall_sample_count: int = 0


class PDGBot(Bot):
    _state: PDGState

    def __init__(self, behavior: str = "pdg") -> None:
        super().__init__()
        self._state = PDGState()
        self.set_identity_name("pdg")
        self._cfg = PDGConfig()
        self._optimizer_boost = self._build_boost_optimizer()
        self._optimizer_terminal = self._build_terminal_optimizer()

        self._behavior = "pdg"
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._thrust_enabled = False
        self._last_target_half = 55.0

        self._plan: PDGPlan | None = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""
        self._solve_count = 0
        self._solve_ms_sum = 0.0
        self._solve_ms_samples: list[float] = []
        self._fallback_frames = 0

        self._auto_target_uid: str | None = None
        self._launch_takeoff_active = False
        self._reset_shape_window_state()
        self._last_flight_snapshot: (
            dict[str, float | int | bool | str | None] | None
        ) = None
        self._debug_boost = os.getenv(
            "PYLANDER_PDG_DEBUG_BOOST", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        self._display_mode: str | None = None
        self._display_phase: str | None = None
        self._display_summary = ""
        self._controllers: dict[FlightStage, StageController] = {
            FlightStage.TAKEOFF: TakeoffBootstrapController(),
            FlightStage.BOOST: PDGBoostController(),
            FlightStage.COAST: BallisticCoastController(),
            FlightStage.TERMINAL: PDGTerminalController(),
            FlightStage.TOUCHDOWN: TouchdownBrakeController(),
        }
        _reset_evaluation_state_impl(self, clear_last_flight_snapshot=True)

        self.set_behavior(behavior)

    @property
    def state(self) -> PDGState:
        return self._state

    def _build_boost_optimizer(self) -> PDGOptimizer:
        return PDGOptimizer(
            PDGOptimizerConfig(
                horizon_steps=36,
                w_terminal_x=48.0,
                w_path_x=0.09,
                w_path_y=0.025,
                w_boost_projected_dx=90.0,
                w_boost_target_y_cross=72.0,
                w_boost_apex=18.0,
                w_boost_angle=44.0,
                w_late_thrust=float(self._cfg.boost_late_thrust_weight),
                boost_angle_slope_target=math.tan(
                    math.radians(float(self._cfg.boost_descent_angle_deg_target))
                ),
            )
        )

    def _build_terminal_optimizer(self) -> PDGOptimizer:
        return PDGOptimizer(
            PDGOptimizerConfig(
                horizon_steps=28,
                w_path_x=_TERMINAL_OPT_PATH_X_WEIGHT,
                w_path_y=_TERMINAL_OPT_PATH_Y_WEIGHT,
                w_upward_vy=_TERMINAL_OPT_UPWARD_VY_WEIGHT,
                w_altitude_progress=_TERMINAL_OPT_ALTITUDE_PROGRESS_WEIGHT,
                w_boost_projected_dx=0.0,
                w_boost_target_y_cross=0.0,
                w_boost_apex=0.0,
                w_boost_angle=0.0,
                w_late_thrust=0.0,
            )
        )

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key != "pdg":
            raise ValueError(f"Unknown pdg behavior '{behavior}'. Expected one of: pdg")
        self._behavior = "pdg"
        self._reset_state()
        self._auto_target_uid = None
        self._launch_takeoff_active = False
        self._last_flight_snapshot = None
        self._transition_to(FlightStage.BOOST, None)

    def supported_eval_goals(self) -> tuple[str, ...]:
        return (EVAL_GOAL_LANDING, EVAL_GOAL_BOOST_CUTOFF)

    def prime_boost_cutoff(self, boost_cutoff: BoostCutoffMetrics) -> None:
        _apply_boost_cutoff_metrics_impl(self, boost_cutoff=boost_cutoff)
        state = self._state
        state._boost_cutoff_spawn_primed = True
        if self._cfg.force_terminal_from_start:
            state._terminal_entry_done = True
            state._terminal_entry_time = 0.0
            state._terminal_entry_altitude = (
                float(boost_cutoff.altitude)
                if boost_cutoff.altitude is not None
                else None
            )
            state._terminal_entry_projected_dx = (
                float(boost_cutoff.projected_impact_dx)
                if boost_cutoff.projected_impact_dx is not None
                else None
            )
            state._terminal_entry_x = (
                float(boost_cutoff.x) if boost_cutoff.x is not None else None
            )
            state._terminal_entry_y = (
                float(boost_cutoff.y) if boost_cutoff.y is not None else None
            )
            state._terminal_post_entry_apex_gain = 0.0
            state._terminal_post_entry_time_to_apex = 0.0
            if boost_cutoff.projected_impact_dx is not None:
                state._terminal_post_entry_peak_abs_dx = abs(
                    float(boost_cutoff.projected_impact_dx)
                )
            elif boost_cutoff.projected_dx is not None:
                state._terminal_post_entry_peak_abs_dx = abs(
                    float(boost_cutoff.projected_dx)
                )
            else:
                state._terminal_post_entry_peak_abs_dx = None
            self._transition_to(FlightStage.TERMINAL, None)
        else:
            self._transition_to(FlightStage.COAST, None)

    def apply_config_override(self, overrides: dict[str, Any]) -> None:
        if not isinstance(overrides, dict):
            raise ValueError("pdg bot config override must be a mapping")
        if not overrides:
            return
        valid_fields = {f.name: f for f in fields(PDGConfig)}
        patch: dict[str, Any] = {}
        for key, raw_value in overrides.items():
            if key not in valid_fields:
                known = ", ".join(sorted(valid_fields))
                raise ValueError(
                    f"Unknown pdg config key '{key}'. Expected one of: {known}"
                )
            current = getattr(self._cfg, key)
            if isinstance(current, bool):
                if not isinstance(raw_value, bool):
                    raise ValueError(f"pdg config key '{key}' must be a boolean")
                patch[key] = bool(raw_value)
            elif isinstance(current, int) and not isinstance(current, bool):
                if isinstance(raw_value, bool):
                    raise ValueError(f"pdg config key '{key}' must be an integer")
                if isinstance(raw_value, float):
                    if not float(raw_value).is_integer():
                        raise ValueError(
                            f"pdg config key '{key}' must be an integer; got {raw_value!r}"
                        )
                    patch[key] = int(raw_value)
                elif isinstance(raw_value, int):
                    patch[key] = int(raw_value)
                else:
                    raise ValueError(f"pdg config key '{key}' must be an integer")
            elif isinstance(current, float):
                if isinstance(raw_value, bool) or not isinstance(
                    raw_value, (int, float)
                ):
                    raise ValueError(f"pdg config key '{key}' must be a number")
                patch[key] = float(raw_value)
            elif isinstance(current, tuple):
                if not isinstance(raw_value, (list, tuple)) or not raw_value:
                    raise ValueError(
                        f"pdg config key '{key}' must be a non-empty list/tuple"
                    )
                parsed: list[int] = []
                for item in raw_value:
                    if isinstance(item, bool) or not isinstance(item, (int, float)):
                        raise ValueError(
                            f"pdg config key '{key}' entries must be integers"
                        )
                    parsed.append(int(item))
                patch[key] = tuple(parsed)
            else:
                raise ValueError(
                    f"pdg config key '{key}' has unsupported type for override"
                )
        self._cfg = replace(self._cfg, **patch)
        self._optimizer_boost = self._build_boost_optimizer()
        self._optimizer_terminal = self._build_terminal_optimizer()

    def _reset_state(self) -> None:
        self._prev_angle_cmd = 0.0
        self._angle_cmd_initialized = False
        self._thrust_enabled = False
        self._plan = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0
        self._last_solve_ms = 0.0
        self._last_solver_status = ""
        self._last_target_half = 55.0
        self._solve_count = 0
        self._solve_ms_sum = 0.0
        self._solve_ms_samples = []
        self._fallback_frames = 0
        self._display_mode = None
        self._display_phase = None
        self._display_summary = ""
        self._launch_takeoff_active = False
        self._stage_tracking_next = FlightStage.BOOST.value
        _reset_evaluation_state_impl(self)

    def _debug_boost_print(self, line: str) -> None:
        if not self._debug_boost:
            return
        print(f"PDGDBG {line}")

    def _set_display_state(
        self,
        *,
        mode: str | None,
        phase: str | None,
        summary: str,
    ) -> None:
        self._display_mode = mode
        self._display_phase = phase
        self._display_summary = summary.strip()

    def _reset_shape_window_state(self) -> None:
        state = self._state
        state._shape_window_started = False
        state._shape_window_done = False
        state._shape_window_start_time = None
        state._shape_window_end_time = None
        state._shape_start_x = 0.0
        state._shape_start_y = 0.0
        state._shape_target_x = 0.0
        state._shape_target_y = 0.0
        state._shape_anchor_dx_abs = 0.0
        state._shape_apex_target_over_target = 0.0
        state._shape_apex_actual_over_target = 0.0
        state._shape_curve_sq_err_sum = 0.0
        state._shape_curve_count = 0
        state._shape_projected_dx_abs_sum = 0.0
        state._shape_projected_dx_abs_max = 0.0
        state._shape_projected_dx_count = 0
        state._shape_shortfall_count = 0
        state._shape_shortfall_sample_count = 0

    @staticmethod
    def _contact_distance(contact) -> float:
        try:
            return abs(float(contact.distance))
        except (TypeError, ValueError):
            rel_x = float(getattr(contact, "rel_x", 0.0))
            rel_y = float(getattr(contact, "rel_y", 0.0))
            return math.hypot(rel_x, rel_y)

    def _landed_contact_uid(self, passive: Sensors) -> str | None:
        contacts = passive.radar_contacts or []
        if not contacts:
            return None
        landed = min(contacts, key=self._contact_distance)
        return landed.uid

    def _resolve_target_contact(self, passive: Sensors):
        contacts = passive.radar_contacts or []
        if not contacts:
            return None

        forced_uid = self.pinned_target_uid or self._auto_target_uid
        if forced_uid:
            for contact in contacts:
                if contact.uid == forced_uid:
                    return contact

        if (
            passive.state == "landed"
            and self.pinned_target_uid is None
            and len(contacts) >= 2
        ):
            landed_uid = self._landed_contact_uid(passive)
            for contact in contacts:
                if contact.uid is not None and contact.uid != landed_uid:
                    self._auto_target_uid = contact.uid
                    return contact

        return pick_target(passive, pinned_uid=self.pinned_target_uid)

    def _takeoff_thrust(self, max_throttle: float) -> float:
        return clamp(self._cfg.launch_takeoff_thrust, 0.0, max_throttle)

    def _reset_with_status(
        self,
        *,
        angle: float,
        status: str,
        mode: str | None = None,
        phase: str | None = None,
        summary: str | None = None,
        clear_targeting: bool = True,
    ) -> BotAction:
        self._reset_state()
        if clear_targeting:
            self._auto_target_uid = None
            self._launch_takeoff_active = False
        action = BotAction(0.0, angle, False, status=status)
        self._set_display_state(
            mode=mode,
            phase=phase,
            summary=summary if summary is not None else status,
        )
        self.status = action.status
        return action

    @property
    def behavior(self) -> str:
        return self._behavior

    @staticmethod
    def _percentile(values: list[float], p: float) -> float:
        return _percentile_impl(values, p)

    def _track_boost_phase_metrics(self, *, dt: float, passive: Sensors) -> None:
        state = self._state
        if state._boost_cutoff_done:
            return
        if state._boost_phase_fuel_start is None:
            state._boost_phase_fuel_start = float(passive.fuel)
        state._boost_phase_thrust_integral += float(passive.thrust_level) * max(
            0.0, float(dt)
        )

    def _boost_cutoff_thrust_is_idle(self, passive: Sensors) -> bool:
        idle_thrust_max = max(0.0, float(self._cfg.boost_cutoff_idle_thrust_max))
        return float(getattr(passive, "thrust_level", 0.0)) <= idle_thrust_max

    def _braking_speed_limit(
        self, alt: float, max_thrust_accel: float, max_tilt: float
    ) -> float:
        cfg = self._cfg
        alt_eff = max(0.0, alt - cfg.braking_alt_margin)
        tilt_eff = cfg.braking_tilt_scale * max_tilt
        vertical_brake = max(
            0.7,
            cfg.braking_accel_safety
            * ((max_thrust_accel * math.cos(tilt_eff)) - _GRAVITY_MAG),
        )
        speed = math.sqrt(
            max(
                0.0,
                (cfg.vy_touch_cap * cfg.vy_touch_cap)
                + (2.0 * vertical_brake * alt_eff),
            )
        )
        return clamp(speed, cfg.braking_min_speed, cfg.braking_max_speed)

    @staticmethod
    def _stable(value: float | None, digits: int) -> float:
        return stable(0.0 if value is None else value, digits)

    def _desired_terminal_vy(
        self, alt: float, max_thrust_accel: float, max_tilt: float
    ) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_target_ratio * self._braking_speed_limit(
            alt, max_thrust_accel, max_tilt
        )
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap)
        return -max(cfg.braking_min_speed, vy_mag)

    def _descent_floor_vy(
        self, alt: float, max_thrust_accel: float, max_tilt: float
    ) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_floor_ratio * self._braking_speed_limit(
            alt, max_thrust_accel, max_tilt
        )
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap + 1.2)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap + 0.3)
        return -max(cfg.braking_min_speed, vy_mag)

    @staticmethod
    def _terminal_lateral_correction_time(
        *, dx: float, vx: float, lateral_accel: float
    ) -> float:
        accel = max(1e-3, float(lateral_accel))
        lateral_speed = float(vx)
        target_dx = float(dx)
        if abs(target_dx) <= 1e-6 and abs(lateral_speed) <= 1e-6:
            return 0.0
        t_stop = abs(lateral_speed) / accel
        x_stop = 0.5 * lateral_speed * t_stop
        residual_dx = target_dx - x_stop
        t_translate = (
            0.0
            if abs(residual_dx) <= 1e-6
            else 2.0 * math.sqrt(abs(residual_dx) / accel)
        )
        return t_stop + t_translate

    def _resolve_static_max_tilt(
        self,
        alt: float,
        dx: float,
        vx: float,
        *,
        dy: float = 0.0,
        phase: str | None = None,
    ) -> float:
        cfg = self._cfg
        if phase == "boost":
            tilt = cfg.boost_max_tilt
            if float(dy) <= -cfg.downhill_boost_dy_min:
                tilt = max(tilt, cfg.downhill_boost_tilt_max)
            if (
                float(dy) >= cfg.uphill_boost_dy_min
                and alt <= cfg.uphill_boost_tilt_alt
            ):
                uphill_tilt_max = cfg.uphill_boost_tilt_max
                if float(dy) <= cfg.uphill_boost_relaxed_dy_max:
                    uphill_tilt_max = max(
                        uphill_tilt_max, cfg.uphill_boost_tilt_relaxed_max
                    )
                tilt = min(tilt, uphill_tilt_max)
            return tilt
        if alt < cfg.low_alt_tilt_alt:
            if abs(dx) <= cfg.low_alt_tilt_dx and abs(vx) <= cfg.low_alt_tilt_vx:
                tilt = cfg.max_tilt_low_alt
            else:
                tilt = cfg.max_tilt_low_alt_far
            return tilt
        return cfg.max_tilt

    def _terminal_tilt_is_recoverable(
        self,
        *,
        tilt: float,
        height_to_target: float,
        lateral_dx: float,
        vx: float,
        vy_up: float,
        max_thrust_accel: float,
    ) -> bool:
        if height_to_target <= 0.0:
            return False
        lateral_accel = max(0.5, float(max_thrust_accel) * math.sin(float(tilt)))
        side_burn_time = self._terminal_lateral_correction_time(
            dx=lateral_dx,
            vx=vx,
            lateral_accel=lateral_accel,
        )
        upward_accel = float(max_thrust_accel) * math.cos(float(tilt))
        net_vertical_accel = upward_accel - _GRAVITY_MAG
        height_after = (
            float(height_to_target)
            + (float(vy_up) * side_burn_time)
            + (0.5 * net_vertical_accel * side_burn_time * side_burn_time)
        )
        if not math.isfinite(height_after) or height_after <= 0.0:
            return False
        vy_after = float(vy_up) + (net_vertical_accel * side_burn_time)
        down_speed_after = max(0.0, -vy_after)
        recover_tilt = self._resolve_static_max_tilt(
            float(height_after),
            0.0,
            0.0,
            dy=-float(height_after),
            phase="terminal",
        )
        recover_limit = self._braking_speed_limit(
            float(height_after),
            float(max_thrust_accel),
            recover_tilt,
        )
        return down_speed_after <= recover_limit

    def _terminal_overshoot_tilt_cap(
        self,
        *,
        alt: float,
        dx: float,
        lateral_dx: float,
        vx: float,
    ) -> float | None:
        cfg = self._cfg
        if alt < float(cfg.terminal_overshoot_tilt_altitude_min):
            return None
        if abs(float(dx)) <= 1e-3 or abs(float(vx)) < float(
            cfg.terminal_overshoot_tilt_vx_min
        ):
            return None
        if float(dx) * float(vx) <= 0.0:
            return None
        if float(dx) * float(lateral_dx) >= 0.0:
            return None

        projected_dx_threshold = max(
            float(cfg.terminal_overshoot_tilt_projected_dx_abs),
            float(cfg.terminal_overshoot_tilt_projected_dx_ratio)
            * float(self._last_target_half),
        )
        projected_dx_abs = abs(float(lateral_dx))
        if projected_dx_abs <= projected_dx_threshold:
            return None

        base_cap = max(float(cfg.terminal_dynamic_tilt_max), 0.0)
        overshoot_cap = max(base_cap, float(cfg.terminal_overshoot_tilt_max))
        if overshoot_cap <= base_cap + 1e-6:
            return None

        severity = clamp(
            (projected_dx_abs - projected_dx_threshold)
            / max(1e-3, projected_dx_threshold),
            0.0,
            1.0,
        )
        return base_cap + (severity * (overshoot_cap - base_cap))

    def _resolve_safe_terminal_max_tilt(
        self,
        alt: float,
        dx: float,
        vx: float,
        *,
        dy: float,
        vy_up: float,
        max_thrust_accel: float,
        lateral_dx: float | None,
    ) -> float:
        base_tilt = self._resolve_static_max_tilt(
            alt,
            dx,
            vx,
            dy=dy,
            phase="terminal",
        )
        dynamic_cap = max(base_tilt, float(self._cfg.terminal_dynamic_tilt_max))
        height_to_target = max(0.0, -float(dy))
        lateral_miss = float(dx) if lateral_dx is None else float(lateral_dx)
        overshoot_cap = self._terminal_overshoot_tilt_cap(
            alt=alt,
            dx=dx,
            lateral_dx=lateral_miss,
            vx=vx,
        )
        if overshoot_cap is not None:
            dynamic_cap = max(dynamic_cap, float(overshoot_cap))
        if dynamic_cap <= base_tilt + 1e-6:
            return base_tilt
        if not self._terminal_tilt_is_recoverable(
            tilt=base_tilt,
            height_to_target=height_to_target,
            lateral_dx=lateral_miss,
            vx=vx,
            vy_up=vy_up,
            max_thrust_accel=max_thrust_accel,
        ):
            return base_tilt
        lo = base_tilt
        hi = dynamic_cap
        if self._terminal_tilt_is_recoverable(
            tilt=hi,
            height_to_target=height_to_target,
            lateral_dx=lateral_miss,
            vx=vx,
            vy_up=vy_up,
            max_thrust_accel=max_thrust_accel,
        ):
            return hi
        for _ in range(8):
            mid = 0.5 * (lo + hi)
            if self._terminal_tilt_is_recoverable(
                tilt=mid,
                height_to_target=height_to_target,
                lateral_dx=lateral_miss,
                vx=vx,
                vy_up=vy_up,
                max_thrust_accel=max_thrust_accel,
            ):
                lo = mid
            else:
                hi = mid
        return lo

    def _resolve_max_tilt(
        self,
        alt: float,
        dx: float,
        vx: float,
        *,
        dy: float = 0.0,
        phase: str | None = None,
        vy_up: float | None = None,
        max_thrust_accel: float | None = None,
        lateral_dx: float | None = None,
    ) -> float:
        if phase == "terminal" and vy_up is not None and max_thrust_accel is not None:
            return self._resolve_safe_terminal_max_tilt(
                alt,
                dx,
                vx,
                dy=dy,
                vy_up=float(vy_up),
                max_thrust_accel=float(max_thrust_accel),
                lateral_dx=lateral_dx,
            )
        return self._resolve_static_max_tilt(
            alt,
            dx,
            vx,
            dy=dy,
            phase=phase,
        )

    def _phase_terminal_x_tol(self, phase: str) -> float:
        cfg = self._cfg
        ratio = cfg.terminal_center_tol_ratio
        if phase == "boost":
            ratio = cfg.boost_center_tol_ratio
        return max(4.0, float(self._last_target_half) * max(0.05, float(ratio)))

    def _shape_apex_target(self, dx_abs: float) -> float:
        cfg = self._cfg
        return clamp(
            float(cfg.boost_apex_height_per_dx) * max(0.0, float(dx_abs)),
            float(cfg.boost_apex_height_min),
            float(cfg.boost_apex_height_max),
        )

    def _boost_distance_alpha(self, dx_abs: float) -> float:
        cfg = self._cfg
        near = float(cfg.boost_distance_scale_near)
        far = max(near + 1.0, float(cfg.boost_distance_scale_far))
        return clamp((max(0.0, float(dx_abs)) - near) / (far - near), 0.0, 1.0)

    def _shape_y_ref(
        self,
        *,
        n: int,
        x0: float,
        y0: float,
        target_x: float,
        target_y: float,
        apex_over_target: float,
    ) -> list[float]:
        den = target_x - x0
        y_ref: list[float] = []
        for idx in range(n + 1):
            alpha = idx / max(1, n)
            xk = x0 + (den * alpha)
            if abs(den) <= 1e-6:
                s = alpha
            else:
                s = clamp((xk - x0) / den, 0.0, 1.0)
            baseline = ((1.0 - s) * y0) + (s * target_y)
            yk = baseline + (4.0 * apex_over_target * s * (1.0 - s))
            y_ref.append(float(yk))
        return y_ref

    def _shape_ref_blend_for_phase(self, phase: str) -> float:
        return 0.0

    def _plan_index(self) -> int:
        if self._plan is None:
            return 0
        step_dt = max(1e-3, float(self._plan.step_dt))
        idx = int(self._plan_elapsed / step_dt)
        return max(0, min(len(self._plan.ax) - 1, idx))

    def _select_optimizer(
        self,
        *,
        phase: str,
        alt: float,
        vy_up: float,
        dy: float = 0.0,
    ) -> PDGOptimizer:
        if phase == "boost":
            return self._optimizer_boost
        if phase in ("terminal", "touchdown"):
            return self._optimizer_terminal
        cfg = self._cfg
        down_speed = max(0.0, -float(vy_up))
        t_go = float("inf") if down_speed <= 1e-3 else (max(0.0, alt) / down_speed)
        if alt >= cfg.long_horizon_altitude or t_go >= cfg.long_horizon_time_to_go:
            return self._optimizer_boost
        return self._optimizer_terminal

    def _replan_policy_for_phase(
        self, phase: str
    ) -> tuple[float, float, float, float, float]:
        cfg = self._cfg
        if phase == "boost":
            return (
                cfg.replan_hz_boost,
                cfg.replan_dx_error_boost,
                cfg.replan_dy_error_boost,
                cfg.replan_vx_error_boost,
                cfg.replan_vy_error_boost,
            )
        if phase in ("terminal", "touchdown"):
            return (
                cfg.replan_hz_terminal,
                cfg.replan_dx_error_terminal,
                cfg.replan_dy_error_terminal,
                cfg.replan_vx_error_terminal,
                cfg.replan_vy_error_terminal,
            )
        return (
            cfg.replan_hz_terminal,
            cfg.replan_dx_error_terminal,
            cfg.replan_dy_error_terminal,
            cfg.replan_vx_error_terminal,
            cfg.replan_vy_error_terminal,
        )

    def _state_deviation_requires_replan(
        self,
        passive: Sensors,
        *,
        dx_err_lim: float,
        dy_err_lim: float,
        vx_err_lim: float,
        vy_err_lim: float,
    ) -> bool:
        if self._plan is None or not self._plan.feasible:
            return True
        idx = self._plan_index()
        err_x = abs(float(passive.x) - float(self._plan.x[idx]))
        err_y = abs(float(passive.y) - float(self._plan.y[idx]))
        err_vx = abs(float(passive.vx) - float(self._plan.vx[idx]))
        err_vy = abs(float(passive.vy_up) - float(self._plan.vy[idx]))
        return (
            err_x > dx_err_lim
            or err_y > dy_err_lim
            or err_vx > vx_err_lim
            or err_vy > vy_err_lim
        )

    def _solve_plan(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
        nominal_thrust_accel: float,
        phase: str,
        projection: BallisticProjection | None = None,
    ) -> PDGPlan | None:
        return _solve_plan_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
            max_thrust_accel=max_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            phase=phase,
            projection=projection,
        )

    def _refresh_stage_tracking(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
        alt: float,
        projection: BallisticProjection,
    ) -> FlightStage:
        token = _refresh_stage_tracking_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
            alt=alt,
            projection=projection,
        )
        return FlightStage(str(token))

    def _maybe_start_shape_window(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
    ) -> None:
        _maybe_start_shape_window_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
        )

    def _shape_reference_y_at_x(self, x: float) -> float:
        state = self._state
        den = state._shape_target_x - state._shape_start_x
        if abs(den) <= 1e-6:
            s = 0.0
        else:
            s = clamp((float(x) - state._shape_start_x) / den, 0.0, 1.0)
        baseline = ((1.0 - s) * state._shape_start_y) + (s * state._shape_target_y)
        return baseline + (4.0 * state._shape_apex_target_over_target * s * (1.0 - s))

    def _update_shape_window_metrics(
        self,
        *,
        passive: Sensors,
        dx: float,
        projection: BallisticProjection,
    ) -> None:
        _update_shape_window_metrics_impl(
            self,
            passive=passive,
            dx=dx,
            projection=projection,
        )

    def _update_terminal_post_entry_metrics(
        self,
        *,
        passive: Sensors,
        dx: float,
    ) -> None:
        _update_terminal_post_entry_metrics_impl(
            self,
            passive=passive,
            dx=dx,
        )

    def _shape_curve_rmse(self) -> float | None:
        state = self._state
        if state._shape_curve_count <= 0:
            return None
        return math.sqrt(
            state._shape_curve_sq_err_sum / max(1, state._shape_curve_count)
        )

    def _shape_projected_dx_abs_mean(self) -> float | None:
        state = self._state
        if state._shape_projected_dx_count <= 0:
            return None
        return state._shape_projected_dx_abs_sum / max(
            1, state._shape_projected_dx_count
        )

    def _shape_shortfall_ratio(self) -> float | None:
        state = self._state
        if state._shape_shortfall_sample_count <= 0:
            return None
        return state._shape_shortfall_count / max(
            1, state._shape_shortfall_sample_count
        )

    def _finalize_terminal_entry(
        self,
        *,
        passive: Sensors,
        dx: float | None,
        alt: float,
        projected_dx: float,
        mode: str,
        horizon_s: float,
        terminal_speed: float | None,
        peak_accel_ratio: float | None,
        od_excess_s: float | None,
        latest_safe_margin_s: float,
        required_accel_ratio: float,
    ) -> None:
        state = self._state
        _finalize_terminal_entry_metrics_impl(
            self,
            passive=passive,
            alt=alt,
            projected_dx=projected_dx,
            dx=dx,
        )
        state._terminal_gate_mode = mode
        state._terminal_gate_horizon_s = horizon_s
        state._terminal_gate_terminal_speed = terminal_speed
        state._terminal_gate_peak_accel_ratio = peak_accel_ratio
        state._terminal_gate_od_excess_s = od_excess_s
        state._terminal_gate_latest_safe_margin_s = latest_safe_margin_s
        state._terminal_gate_required_accel_ratio = required_accel_ratio

    def _evaluate_terminal_gate(
        self,
        *,
        dt: float,
        passive: Sensors,
        dx: float,
        projected_dx: float | None,
        dy: float,
        alt: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
        nominal_thrust_accel: float,
        thrust_ramp_up: float,
    ):
        return _evaluate_terminal_gate_impl(
            self,
            dt=dt,
            passive=passive,
            dx=dx,
            projected_dx=projected_dx,
            dy=dy,
            alt=alt,
            max_thrust_accel=max_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            thrust_ramp_up=thrust_ramp_up,
        )

    def _command_from_plan(
        self,
        *,
        dt: float,
        passive: Sensors,
        dx: float,
        projected_dx: float | None,
        dy: float,
        alt: float,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
        max_thrust_accel: float,
    ) -> BotAction:
        return _command_from_plan_impl(
            self,
            dt=dt,
            passive=passive,
            dx=dx,
            projected_dx=projected_dx,
            dy=dy,
            alt=alt,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            max_thrust_accel=max_thrust_accel,
        )

    def _command_passive_coast(
        self,
        *,
        dt: float,
        passive: Sensors,
    ) -> BotAction:
        return _command_passive_coast_impl(
            self,
            dt=dt,
            passive=passive,
        )

    def _command_boost_settle(
        self,
        *,
        dt: float,
        passive: Sensors,
    ) -> BotAction:
        hold_angle = self._state._boost_cut_hold_angle
        if hold_angle is None:
            return self._command_passive_coast(dt=dt, passive=passive)
        return _command_zero_thrust_hold_angle_impl(
            self,
            dt=dt,
            hold_angle=float(hold_angle),
        )

    def _evaluate_boost_quality(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
        projection: BallisticProjection,
    ):
        state = self._state
        dx_anchor_abs = (
            state._shape_anchor_dx_abs
            if state._shape_window_started
            else abs(float(dx))
        )
        return _evaluate_boost_quality_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
            projection=projection,
            dx_anchor_abs=dx_anchor_abs,
        )

    def _evaluate_boost_quality_after_settle(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
        settle_s: float,
        settle_angle_target: float | None = None,
    ):
        state = self._state
        dx_anchor_abs = (
            state._shape_anchor_dx_abs
            if state._shape_window_started
            else abs(float(dx))
        )
        return _evaluate_boost_quality_after_settle_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
            settle_s=settle_s,
            dx_anchor_abs=dx_anchor_abs,
            settle_angle_target=settle_angle_target,
        )

    def _boost_cut_wind_down_s(
        self,
        *,
        passive: Sensors,
        minimum_s: float,
    ) -> float:
        return _boost_cut_wind_down_s_impl(
            self,
            passive=passive,
            minimum_s=minimum_s,
        )

    def _boost_settle_hold_angle(
        self,
        *,
        dy: float,
    ) -> float | None:
        transfer_dy = _transfer_dy_for_boost_impl(self, dy=dy)
        if transfer_dy < float(self._cfg.uphill_boost_dy_min):
            return None
        return float(self._prev_angle_cmd)

    def _run_boost_controller(
        self,
        *,
        ctx: UpdateContext,
    ) -> StageTickResult:
        state = self._state
        if (
            ctx.suggested_stage != FlightStage.BOOST
            and (not state._boost_cut_latched)
            and (not state._boost_cutoff_done)
        ):
            return StageTickResult(next_stage=ctx.suggested_stage)

        quality = self._evaluate_boost_quality(
            passive=ctx.passive,
            dx=ctx.dx,
            dy=ctx.dy,
            projection=ctx.projection,
        )
        state._boost_quality_verdict = quality.verdict

        if state._boost_cut_latched:
            action = self._command_boost_settle(dt=ctx.dt, passive=ctx.passive)
            action.status = f"pdg settle/boost {quality.verdict}"
            self._set_display_state(
                mode="passive", phase="boost", summary=f"cut {quality.verdict}"
            )
            if self._boost_cutoff_thrust_is_idle(ctx.passive):
                _finalize_boost_cutoff_metrics_impl(
                    self,
                    passive=ctx.passive,
                    alt=ctx.alt,
                    projection=ctx.projection,
                )
                state._boost_cutoff_quality_pass = bool(quality.passed)
                state._boost_cutoff_quality_verdict = quality.verdict
                state._debug_boost_post_end_time = state._elapsed_time_s + 4.0
                return StageTickResult(action=action, next_stage=FlightStage.COAST)
            return StageTickResult(action=action)

        action = self._run_pdg_stage(ctx=ctx, stage=FlightStage.BOOST)
        planner_target_thrust = float(action.target_thrust)
        boost_cut_thrust = float(self._cfg.boost_cutoff_burn_start_thrust)
        boost_thrust_floor_ratio = float(self._cfg.boost_active_thrust_floor)
        if float(ctx.dy) >= float(self._cfg.uphill_boost_dy_min):
            state = self._state
            dx_anchor_abs = (
                state._shape_anchor_dx_abs
                if state._shape_window_started
                else abs(float(ctx.dx))
            )
            distance_alpha = self._boost_distance_alpha(dx_anchor_abs)
            boost_cut_thrust = (
                (1.0 - distance_alpha)
                * float(self._cfg.boost_cutoff_burn_start_thrust_near)
            ) + (distance_alpha * float(self._cfg.boost_cutoff_burn_start_thrust_far))
            boost_thrust_floor_ratio = (
                (1.0 - distance_alpha) * float(self._cfg.boost_active_thrust_floor_near)
            ) + (distance_alpha * float(self._cfg.boost_active_thrust_floor_far))
        if (not quality.passed) and abs(float(ctx.dx)) > 1e-3:
            state._boost_burn_started = True
            state._boost_burn_idle_since = None
            if state._boost_burn_start_time is None:
                state._boost_burn_start_time = state._elapsed_time_s
        settled_quality = quality
        if state._boost_burn_started:
            settle_s = self._boost_cut_wind_down_s(
                passive=ctx.passive,
                minimum_s=float(self._cfg.boost_cutoff_burn_end_settle_s),
            )
            settle_angle_target = self._boost_settle_hold_angle(dy=ctx.dy)
            settled_quality = self._evaluate_boost_quality_after_settle(
                passive=ctx.passive,
                dx=ctx.dx,
                dy=ctx.dy,
                settle_s=settle_s,
                settle_angle_target=settle_angle_target,
            )
        overshot_target_direction = (
            quality.projected_dx is not None
            and abs(float(ctx.dx)) > 1e-3
            and (float(quality.projected_dx) * float(ctx.dx)) < 0.0
        )
        if settled_quality.passed and state._boost_burn_started:
            state._boost_cut_latched = True
            state._boost_settle_start_time = state._elapsed_time_s
            state._boost_cut_hold_angle = self._boost_settle_hold_angle(dy=ctx.dy)
            state._boost_cutoff_quality_pass = True
            state._boost_cutoff_quality_verdict = settled_quality.verdict
            settle_action = self._command_boost_settle(dt=ctx.dt, passive=ctx.passive)
            settle_action.status = "pdg settle/boost pass"
            self._set_display_state(mode="passive", phase="boost", summary="cut pass")
            return StageTickResult(action=settle_action)
        if state._boost_burn_started and (not quality.passed):
            burn_elapsed = state._elapsed_time_s - float(
                state._boost_burn_start_time or state._elapsed_time_s
            )
            if quality.verdict != "no_target_y_solution":
                if overshot_target_direction and burn_elapsed >= 0.75:
                    state._boost_cut_latched = True
                    state._boost_settle_start_time = state._elapsed_time_s
                    state._boost_cut_hold_angle = self._boost_settle_hold_angle(
                        dy=ctx.dy
                    )
                    state._boost_cutoff_quality_pass = False
                    state._boost_cutoff_quality_verdict = quality.verdict
                    settle_action = self._command_boost_settle(
                        dt=ctx.dt, passive=ctx.passive
                    )
                    settle_action.status = f"pdg settle/boost {quality.verdict}"
                    self._set_display_state(
                        mode="passive",
                        phase="boost",
                        summary=f"cut {quality.verdict}",
                    )
                    return StageTickResult(action=settle_action)
                if burn_elapsed >= float(self._cfg.boost_burn_max_s):
                    state._boost_cut_latched = True
                    state._boost_settle_start_time = state._elapsed_time_s
                    state._boost_cut_hold_angle = self._boost_settle_hold_angle(
                        dy=ctx.dy
                    )
                    state._boost_cutoff_quality_pass = False
                    state._boost_cutoff_quality_verdict = quality.verdict
                    settle_action = self._command_boost_settle(
                        dt=ctx.dt, passive=ctx.passive
                    )
                    settle_action.status = f"pdg settle/boost {quality.verdict}"
                    self._set_display_state(
                        mode="passive",
                        phase="boost",
                        summary=f"cut {quality.verdict}",
                    )
                    return StageTickResult(action=settle_action)
                state._boost_burn_idle_since = None
            else:
                if planner_target_thrust < boost_cut_thrust and burn_elapsed >= 0.75:
                    if state._boost_burn_idle_since is None:
                        state._boost_burn_idle_since = state._elapsed_time_s
                else:
                    state._boost_burn_idle_since = None
                idle_elapsed = 0.0
                if state._boost_burn_idle_since is not None:
                    idle_elapsed = state._elapsed_time_s - float(
                        state._boost_burn_idle_since
                    )
                if burn_elapsed >= float(self._cfg.boost_burn_max_s) or (
                    state._boost_burn_idle_since is not None
                    and idle_elapsed >= float(self._cfg.boost_failure_cut_idle_s)
                ):
                    state._boost_cut_latched = True
                    state._boost_settle_start_time = state._elapsed_time_s
                    state._boost_cut_hold_angle = self._boost_settle_hold_angle(
                        dy=ctx.dy
                    )
                    state._boost_cutoff_quality_pass = False
                    state._boost_cutoff_quality_verdict = quality.verdict
                    settle_action = self._command_boost_settle(
                        dt=ctx.dt, passive=ctx.passive
                    )
                    settle_action.status = f"pdg settle/boost {quality.verdict}"
                    self._set_display_state(
                        mode="passive",
                        phase="boost",
                        summary=f"cut {quality.verdict}",
                    )
                    return StageTickResult(action=settle_action)
            thrust_floor = min(
                float(ctx.max_throttle),
                boost_thrust_floor_ratio * float(ctx.max_throttle),
            )
            if (not overshot_target_direction) and planner_target_thrust < thrust_floor:
                action.target_thrust = thrust_floor
            self._thrust_enabled = True

        action.status = f"pdg opt/boost {quality.verdict}"
        if (
            self._debug_boost
            and (state._elapsed_time_s - state._debug_boost_last_print_t) >= 0.24
        ):
            state._debug_boost_last_print_t = state._elapsed_time_s
            self._debug_boost_print(
                "boost_cmd "
                f"t={state._elapsed_time_s:6.2f} "
                f"cmd_thrust={float(action.target_thrust):5.2f} "
                f"cmd_angle={math.degrees(float(action.target_angle)):6.2f} "
                f"q={quality.verdict}"
            )
        self._set_display_state(
            mode="opt",
            phase="boost",
            summary=(
                f"dx={stable(ctx.dx, 1):.1f} "
                f"pdx={stable(float(ctx.projection.projected_dx), 1):.1f} "
                f"q={quality.verdict}"
            ),
        )
        return StageTickResult(action=action)

    def _transition_to(self, stage: FlightStage, ctx: UpdateContext | None) -> None:
        state = self._state
        current = state._active_stage
        if current == stage:
            state._active_phase = stage.value
            if stage == FlightStage.TAKEOFF:
                self._launch_takeoff_active = True
            elif stage != FlightStage.TAKEOFF:
                self._launch_takeoff_active = False
            return
        if isinstance(current, FlightStage) and current in self._controllers:
            self._controllers[current].exit(self, ctx)
        state._active_stage = stage
        state._active_phase = stage.value
        self._launch_takeoff_active = stage == FlightStage.TAKEOFF
        if stage in (FlightStage.TAKEOFF, FlightStage.COAST):
            self._thrust_enabled = False
            self._plan = None
            self._plan_elapsed = 0.0
            self._replan_timer = 0.0
            self._fallback_steps_remaining = 0
        elif stage in (FlightStage.BOOST, FlightStage.TERMINAL):
            self._plan = None
            self._plan_elapsed = 0.0
            self._replan_timer = 0.0
            self._fallback_steps_remaining = int(self._cfg.fallback_hold_steps)
        if stage == FlightStage.BOOST:
            state = self._state
            state._boost_cut_latched = False
            state._boost_cut_hold_angle = None
            state._boost_settle_start_time = None
            state._boost_quality_verdict = None
            state._boost_burn_start_time = None
        if stage in self._controllers:
            self._controllers[stage].enter(self, ctx)

    def _build_update_context(
        self,
        *,
        dt: float,
        passive: Sensors,
        target: Any | None,
        dx: float,
        dy: float,
        alt: float,
        projection: BallisticProjection,
        max_power: float,
        min_throttle: float,
        max_throttle: float,
        ramp_up: float,
        max_thrust_accel: float,
        nominal_thrust_accel: float,
        min_thrust_accel: float,
        suggested_stage: FlightStage,
    ) -> UpdateContext:
        return UpdateContext(
            dt=dt,
            passive=passive,
            target=target,
            dx=dx,
            dy=dy,
            alt=alt,
            projection=projection,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            max_thrust_accel=max_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            suggested_stage=suggested_stage,
        )

    def _run_pdg_stage(
        self,
        *,
        ctx: UpdateContext,
        stage: FlightStage,
    ) -> BotAction:
        phase = stage.value
        replan_hz, dx_err_lim, dy_err_lim, vx_err_lim, vy_err_lim = (
            self._replan_policy_for_phase(phase)
        )

        self._replan_timer -= max(0.0, ctx.dt)
        self._plan_elapsed += max(0.0, ctx.dt)

        need_replan = (
            self._plan is None
            or not self._plan.feasible
            or self._replan_timer <= 0.0
            or self._state_deviation_requires_replan(
                ctx.passive,
                dx_err_lim=dx_err_lim,
                dy_err_lim=dy_err_lim,
                vx_err_lim=vx_err_lim,
                vy_err_lim=vy_err_lim,
            )
        )

        if need_replan:
            plan = self._solve_plan(
                passive=ctx.passive,
                dx=ctx.dx,
                dy=ctx.dy,
                max_thrust_accel=ctx.max_thrust_accel,
                min_thrust_accel=ctx.min_thrust_accel,
                nominal_thrust_accel=ctx.nominal_thrust_accel,
                phase=phase,
                projection=ctx.projection,
            )
            if plan is not None and plan.feasible:
                self._plan = plan
                self._plan_elapsed = 0.0
                self._replan_timer = 1.0 / max(1e-3, replan_hz)
                self._fallback_steps_remaining = int(self._cfg.fallback_hold_steps)
            else:
                if (
                    self._fallback_steps_remaining > 0
                    and self._plan is not None
                    and self._plan.feasible
                ):
                    self._fallback_steps_remaining -= 1
                else:
                    self._plan = None

        action = self._command_from_plan(
            dt=ctx.dt,
            passive=ctx.passive,
            dx=ctx.dx,
            projected_dx=float(ctx.projection.projected_dx),
            dy=ctx.dy,
            alt=ctx.alt,
            max_power=ctx.max_power,
            min_throttle=ctx.min_throttle,
            max_throttle=ctx.max_throttle,
            max_thrust_accel=ctx.max_thrust_accel,
        )
        mode = "opt"
        if self._plan is None or not self._plan.feasible:
            mode = "fallback"
            self._fallback_frames += 1
        action.status = (
            f"pdg {mode}/{phase} "
            f"dx={stable(ctx.dx, 1):.1f} pdx={stable(float(ctx.projection.projected_dx), 1):.1f}"
        )
        self._set_display_state(
            mode=mode,
            phase=phase,
            summary=(
                f"dx={stable(ctx.dx, 1):.1f} "
                f"pdx={stable(float(ctx.projection.projected_dx), 1):.1f}"
            ),
        )
        return action

    def update(self, dt: float, sensors: Sensors) -> BotAction:
        passive = sensors
        state = self._state
        if passive.state == "crashed":
            return self._reset_with_status(
                angle=passive.angle,
                status="pdg crashed",
                mode="idle",
                phase="crashed",
                summary="crashed",
            )
        if passive.state == "out_of_fuel":
            return self._reset_with_status(
                angle=passive.angle,
                status="pdg out_of_fuel",
                mode="idle",
                phase="out_of_fuel",
                summary="out of fuel",
            )

        if passive.state == "landed":
            self._reset_state()
            self._transition_to(FlightStage.BOOST, None)

        max_power, min_throttle, max_throttle, ramp_up = engine_profile(
            self.vehicle_info
        )
        target = self._resolve_target_contact(passive)
        target_uid = target.uid if target is not None else None
        alt = max(0.0, finite_altitude(passive))
        mass = max(0.5, float(passive.mass))
        max_force = max_power * max_throttle
        nominal_force = max_power * min(1.0, max_throttle)
        min_force = max_power * min_throttle
        max_thrust_accel = max(0.1, max_force / mass)
        nominal_thrust_accel = max(0.1, nominal_force / mass)
        min_thrust_accel = max(0.0, min_force / mass)

        if passive.state == "landed":
            landed_uid = self._landed_contact_uid(passive)
            if target_uid is None or landed_uid == target_uid:
                self._launch_takeoff_active = False
                action = BotAction(0.0, 0.0, False, status="pdg landed")
                self._set_display_state(mode="idle", phase="landed", summary="landed")
                self.status = action.status
                return action
            self._transition_to(FlightStage.TAKEOFF, None)
            takeoff_ctx = self._build_update_context(
                dt=dt,
                passive=passive,
                target=target,
                dx=0.0,
                dy=0.0,
                alt=alt,
                projection=estimate_target_y_projection(
                    dx=0.0,
                    dy=0.0,
                    vx=float(passive.vx),
                    vy_up=float(passive.vy_up),
                    x=float(passive.x),
                    y=float(passive.y),
                ),
                max_power=max_power,
                min_throttle=min_throttle,
                max_throttle=max_throttle,
                ramp_up=ramp_up,
                max_thrust_accel=max_thrust_accel,
                nominal_thrust_accel=nominal_thrust_accel,
                min_thrust_accel=min_thrust_accel,
                suggested_stage=FlightStage.TAKEOFF,
            )
            action = (
                self._controllers[FlightStage.TAKEOFF].update(self, takeoff_ctx).action
            )
            if action is None:
                raise RuntimeError("pdg takeoff stage did not produce an action")
            self.status = action.status
            self._last_flight_snapshot = self._build_evaluation_snapshot()
            return action

        if passive.state != "flying":
            return self._reset_with_status(
                angle=passive.angle,
                status=f"pdg {passive.state}",
                mode="idle",
                phase=str(passive.state),
                summary=str(passive.state),
            )
        if (
            self._last_flight_snapshot is not None
            and state._elapsed_time_s <= 1e-9
            and self._solve_count == 0
        ):
            # New run after a reset: discard prior episode telemetry.
            self._last_flight_snapshot = None

        if not self._angle_cmd_initialized:
            self._prev_angle_cmd = float(passive.angle)
            self._angle_cmd_initialized = True

        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            self._last_target_half = target_half_width(getattr(target, "size", None))
            state._last_target_y = float(target.y)
            state._peak_alt_over_target = max(
                state._peak_alt_over_target,
                max(0.0, float(passive.y) - state._last_target_y),
            )
            state._clearance_margin = 0.0
            state._clearance_scale = 0.0
            state._clearance_active = False
        else:
            dx = 0.0
            dy = -max(0.0, finite_altitude(passive))
            state._last_target_y = 0.0
            state._clearance_margin = 0.0
            state._clearance_scale = 0.0
            state._clearance_active = False

        state._elapsed_time_s += max(0.0, float(dt))
        self._track_boost_phase_metrics(dt=dt, passive=passive)
        self._maybe_start_shape_window(passive=passive, dx=dx, dy=dy)
        projection = estimate_target_y_projection(
            dx=dx,
            dy=dy,
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            x=float(passive.x),
            y=float(passive.y),
        )
        suggested_stage = self._refresh_stage_tracking(
            passive=passive,
            dx=dx,
            dy=dy,
            alt=alt,
            projection=projection,
        )
        self._update_shape_window_metrics(
            passive=passive,
            dx=dx,
            projection=projection,
        )
        ctx = self._build_update_context(
            dt=dt,
            passive=passive,
            target=target,
            dx=dx,
            dy=dy,
            alt=alt,
            projection=projection,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            ramp_up=ramp_up,
            max_thrust_accel=max_thrust_accel,
            nominal_thrust_accel=nominal_thrust_accel,
            min_thrust_accel=min_thrust_accel,
            suggested_stage=suggested_stage,
        )
        for _ in range(6):
            active_stage = self._state._active_stage or FlightStage.BOOST
            controller = self._controllers[active_stage]
            result = controller.update(self, ctx)
            if result.next_stage is not None and result.next_stage != active_stage:
                self._transition_to(result.next_stage, ctx)
                continue
            action = result.action
            break
        else:
            raise RuntimeError("pdg stage router exceeded transition budget")
        if action is None:
            raise RuntimeError(
                f"pdg stage '{self._state._active_phase}' did not produce an action"
            )
        self._update_terminal_post_entry_metrics(passive=passive, dx=dx)
        self.status = action.status
        self._last_flight_snapshot = self._build_evaluation_snapshot()
        return action

    def _build_evaluation_snapshot(self) -> dict[str, float | int | bool | str | None]:
        return _build_evaluation_snapshot_impl(self)

    def get_bot_telemetry(self) -> dict[str, float | int | bool | str | None]:
        return _resolve_evaluation_snapshot_impl(self)

    def get_display_state(self) -> BotDisplayState | None:
        state = self._state
        return BotDisplayState(
            bot_name="pdg",
            mode=self._display_mode,
            phase=self._display_phase or state._active_phase,
            summary=self._display_summary,
        )

    def get_flight_phase_snapshot(self) -> FlightPhaseSnapshot | None:
        state = self._state
        milestones: tuple[str, ...] = (
            ("boost_cutoff",) if state._boost_cutoff_done else ()
        )
        boost_cutoff = None
        if state._boost_cutoff_done:
            boost_cutoff = BoostCutoffMetrics(
                time_s=state._boost_cutoff_time,
                altitude=state._boost_cutoff_altitude,
                x=state._boost_cutoff_x,
                y=state._boost_cutoff_y,
                vx=state._boost_cutoff_vx,
                vy_up=state._boost_cutoff_vy_up,
                projected_apex_y=state._boost_cutoff_projected_apex_y,
                projected_apex_over_target=state._boost_cutoff_projected_apex_over_target,
                has_target_y_solution=state._boost_cutoff_has_target_y_solution,
                projected_dx=state._boost_cutoff_projected_dx,
                projected_impact_dx=state._boost_cutoff_projected_impact_dx,
                projected_impact_angle_deg=state._boost_cutoff_projected_impact_angle_deg,
                burn_duration_s=state._boost_cutoff_burn_duration_s,
                burn_fuel_used=state._boost_cutoff_burn_fuel_used,
                burn_avg_thrust_level=state._boost_cutoff_burn_avg_thrust_level,
            )
        return FlightPhaseSnapshot(
            phase=state._active_phase,
            milestones=milestones,
            boost_cutoff=boost_cutoff,
        )

    def get_plot_markers(self) -> tuple[PlotMarker, ...]:
        state = self._state
        out: list[PlotMarker] = []
        if state._boost_cutoff_done:
            out.append(
                PlotMarker(
                    id="boost_cutoff",
                    name="boost_cutoff",
                    label="boost cutoff",
                    x=state._boost_cutoff_x,
                    y=state._boost_cutoff_y,
                    metadata={
                        "time_s": state._boost_cutoff_time,
                        "vx": state._boost_cutoff_vx,
                        "vy_up": state._boost_cutoff_vy_up,
                    },
                )
            )
        if state._terminal_entry_done:
            label = "terminal"
            if state._terminal_gate_mode:
                if state._terminal_gate_mode == "nominal_ready":
                    mode_label = "ready"
                elif state._terminal_gate_mode == "terrain_divert":
                    mode_label = "terrain"
                else:
                    mode_label = "late"
                label = f"{label} {mode_label}"
            if state._terminal_entry_projected_dx is not None:
                label = (
                    f"{label} dx={stable(state._terminal_entry_projected_dx, 1):.1f}"
                )
            metadata: dict[str, float | str | None] = {
                "time_s": state._terminal_entry_time
            }
            if state._terminal_gate_mode is not None:
                metadata["mode"] = state._terminal_gate_mode
            if state._terminal_gate_horizon_s is not None:
                metadata["horizon_s"] = state._terminal_gate_horizon_s
            out.append(
                PlotMarker(
                    id="terminal_entry",
                    name="terminal_entry",
                    label=label,
                    x=state._terminal_entry_x,
                    y=state._terminal_entry_y,
                    metadata=metadata,
                )
            )
        if (
            state._terrain_divert_mode is not None
            and state._terrain_divert_worst_x is not None
            and self.environment is not None
        ):
            terrain_y = self.environment.terrain.sample_height(
                float(state._terrain_divert_worst_x),
                lod=0,
            )
            metadata: dict[str, float | str | None] = {
                "mode": state._terrain_divert_mode,
                "margin": state._terrain_divert_margin_min,
                "limit_t": state._terrain_divert_first_limit_t,
                "horizon_s": state._terrain_divert_horizon_s,
            }
            out.append(
                PlotMarker(
                    id="terrain_divert",
                    name="terrain_divert",
                    label="terrain divert",
                    x=state._terrain_divert_worst_x,
                    y=terrain_y,
                    metadata=metadata,
                )
            )
        return tuple(out)

    def get_evaluation_decision(self) -> BotEvalDecision | None:
        return _build_evaluation_decision_impl(self)


def create_bot() -> Bot:
    return PDGBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("pdg",)


__all__ = [
    "FlightStage",
    "PDGBot",
    "UpdateContext",
    "create_bot",
    "list_behavior_names",
]
