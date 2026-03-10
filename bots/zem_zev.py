"""Optimizer-first powered descent bot (ZEM/ZEV replacement).

This version uses a receding-horizon convex optimizer to generate coupled
horizontal/vertical thrust commands from a single objective each replan cycle.
"""

from __future__ import annotations

import math
import os
from dataclasses import fields, replace
from typing import Any

from bots._ballistics import (
    BallisticProjection,
    estimate_target_y_projection,
)
from bots._bot_math import clamp, engine_profile, finite_altitude, stable
from bots._zem_gate import evaluate_flare_gate as _evaluate_flare_gate_impl
from bots._zem_actuation import (
    command_from_plan as _command_from_plan_impl,
    command_passive_coast as _command_passive_coast_impl,
)
from bots._zem_config import ZemZevConfig
from bots._zem_eval import (
    build_evaluation_decision as _build_evaluation_decision_impl,
    build_evaluation_snapshot as _build_evaluation_snapshot_impl,
    percentile as _percentile_impl,
    reset_evaluation_state as _reset_evaluation_state_impl,
    resolve_evaluation_snapshot as _resolve_evaluation_snapshot_impl,
)
from bots._zem_phase import (
    apply_setup_gate_metrics as _apply_setup_gate_metrics_impl,
    finalize_terminal_gate_metrics as _finalize_terminal_gate_metrics_impl,
    maybe_start_shape_window as _maybe_start_shape_window_impl,
    update_phase_tracking as _update_phase_tracking_impl,
    update_shape_window_metrics as _update_shape_window_metrics_impl,
)
from bots._zem_planner import solve_plan as _solve_plan_impl
from bots._optimizer_pdg import PDGOptimizer, PDGOptimizerConfig, PDGPlan
from bots._targeting import pick_target, target_half_width
from core.bot import (
    Bot,
    BotAction,
    BotDisplayState,
    BotEvalDecision,
    FlightPhaseSnapshot,
    PlotMarker,
    Sensors,
    SetupGateMetrics,
)
from core.config import GRAVITY
from core.eval_goals import EVAL_GOAL_LANDING, EVAL_GOAL_SETUP

_GRAVITY_MAG = abs(float(GRAVITY))


class ZemZevBot(Bot):
    def __init__(self, behavior: str = "zem_zev") -> None:
        super().__init__()
        self._cfg = ZemZevConfig()
        self._optimizer_setup = PDGOptimizer(
            PDGOptimizerConfig(
                horizon_steps=36,
                w_terminal_x=48.0,
                w_path_x=0.09,
                w_path_y=0.025,
            )
        )
        self._optimizer_terminal = PDGOptimizer(PDGOptimizerConfig(horizon_steps=28))
        self._optimizer_flare_probe: dict[int, PDGOptimizer] = {}
        self._rebuild_flare_probe_optimizers()

        self._behavior = "zem_zev"
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
        self._last_flight_snapshot: dict[str, float | int | bool | str | None] | None = None
        self._debug_setup = (
            os.getenv("PYLANDER_ZEM_DEBUG_SETUP", "").strip().lower() in ("1", "true", "yes", "on")
        )
        self._display_mode: str | None = None
        self._display_phase: str | None = None
        self._display_summary = ""
        _reset_evaluation_state_impl(self, clear_last_flight_snapshot=True)

        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key != "zem_zev":
            raise ValueError(
                f"Unknown zem_zev behavior '{behavior}'. Expected one of: zem_zev"
            )
        self._behavior = "zem_zev"
        self._reset_state()
        self._auto_target_uid = None
        self._launch_takeoff_active = False
        self._last_flight_snapshot = None

    def supported_eval_goals(self) -> tuple[str, ...]:
        return (EVAL_GOAL_LANDING, EVAL_GOAL_SETUP)

    def prime_setup_gate(self, setup_gate: SetupGateMetrics) -> None:
        _apply_setup_gate_metrics_impl(self, setup_gate=setup_gate)
        self._setup_gate_spawn_primed = True
        self._active_phase = "coast"
        self._thrust_enabled = False
        self._plan = None
        self._plan_elapsed = 0.0
        self._replan_timer = 0.0
        self._fallback_steps_remaining = 0

    def apply_config_override(self, overrides: dict[str, Any]) -> None:
        if not isinstance(overrides, dict):
            raise ValueError("zem_zev bot config override must be a mapping")
        if not overrides:
            return
        valid_fields = {f.name: f for f in fields(ZemZevConfig)}
        patch: dict[str, Any] = {}
        for key, raw_value in overrides.items():
            if key not in valid_fields:
                known = ", ".join(sorted(valid_fields))
                raise ValueError(
                    f"Unknown zem_zev config key '{key}'. Expected one of: {known}"
                )
            current = getattr(self._cfg, key)
            if isinstance(current, bool):
                if not isinstance(raw_value, bool):
                    raise ValueError(f"zem_zev config key '{key}' must be a boolean")
                patch[key] = bool(raw_value)
            elif isinstance(current, int) and not isinstance(current, bool):
                if isinstance(raw_value, bool):
                    raise ValueError(f"zem_zev config key '{key}' must be an integer")
                if isinstance(raw_value, float):
                    if not float(raw_value).is_integer():
                        raise ValueError(
                            f"zem_zev config key '{key}' must be an integer; got {raw_value!r}"
                        )
                    patch[key] = int(raw_value)
                elif isinstance(raw_value, int):
                    patch[key] = int(raw_value)
                else:
                    raise ValueError(f"zem_zev config key '{key}' must be an integer")
            elif isinstance(current, float):
                if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                    raise ValueError(f"zem_zev config key '{key}' must be a number")
                patch[key] = float(raw_value)
            elif isinstance(current, tuple):
                if not isinstance(raw_value, (list, tuple)) or not raw_value:
                    raise ValueError(
                        f"zem_zev config key '{key}' must be a non-empty list/tuple"
                    )
                parsed: list[int] = []
                for item in raw_value:
                    if isinstance(item, bool) or not isinstance(item, (int, float)):
                        raise ValueError(
                            f"zem_zev config key '{key}' entries must be integers"
                        )
                    parsed.append(int(item))
                patch[key] = tuple(parsed)
            else:
                raise ValueError(
                    f"zem_zev config key '{key}' has unsupported type for override"
                )
        self._cfg = replace(self._cfg, **patch)
        self._rebuild_flare_probe_optimizers()

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
        _reset_evaluation_state_impl(self)

    def _debug_setup_print(self, line: str) -> None:
        if not self._debug_setup:
            return
        print(f"ZEMDBG {line}")

    def _rebuild_flare_probe_optimizers(self) -> None:
        unique_steps = sorted({max(16, int(step)) for step in self._cfg.flare_gate_horizon_steps})
        self._optimizer_flare_probe = {
            steps: PDGOptimizer(
                PDGOptimizerConfig(
                    horizon_steps=steps,
                    w_terminal_x=180.0,
                    w_terminal_y=220.0,
                    w_terminal_vx=120.0,
                    w_terminal_vy=60.0,
                    w_effort=0.005,
                    w_smooth=0.05,
                    w_path_x=0.0,
                    w_path_y=0.0,
                    w_upward_vy=0.5,
                    w_descent_floor=0.1,
                    w_altitude_progress=0.0,
                    w_downspeed_progress=0.0,
                    w_thrust_linear=0.05,
                    w_overdrive_linear=2.0,
                    w_overdrive_quadratic=8.0,
                )
            )
            for steps in unique_steps
        }

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
        self._shape_window_started = False
        self._shape_window_done = False
        self._shape_window_start_time: float | None = None
        self._shape_window_end_time: float | None = None
        self._shape_start_x = 0.0
        self._shape_start_y = 0.0
        self._shape_target_x = 0.0
        self._shape_target_y = 0.0
        self._shape_anchor_dx_abs = 0.0
        self._shape_apex_target_over_target = 0.0
        self._shape_apex_actual_over_target = 0.0
        self._shape_curve_sq_err_sum = 0.0
        self._shape_curve_count = 0
        self._shape_projected_dx_abs_sum = 0.0
        self._shape_projected_dx_abs_max = 0.0
        self._shape_projected_dx_count = 0
        self._shape_shortfall_count = 0
        self._shape_shortfall_sample_count = 0

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

        if passive.state == "landed" and self.pinned_target_uid is None and len(contacts) >= 2:
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

    def _track_setup_phase_metrics(self, *, dt: float, passive: Sensors) -> None:
        if self._setup_gate_done:
            return
        if self._setup_phase_fuel_start is None:
            self._setup_phase_fuel_start = float(passive.fuel)
        self._setup_phase_thrust_integral += float(passive.thrust_level) * max(0.0, float(dt))

    def _braking_speed_limit(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        alt_eff = max(0.0, alt - cfg.braking_alt_margin)
        tilt_eff = cfg.braking_tilt_scale * max_tilt
        vertical_brake = max(
            0.7,
            cfg.braking_accel_safety * ((max_thrust_accel * math.cos(tilt_eff)) - _GRAVITY_MAG),
        )
        speed = math.sqrt(max(0.0, (cfg.vy_touch_cap * cfg.vy_touch_cap) + (2.0 * vertical_brake * alt_eff)))
        return clamp(speed, cfg.braking_min_speed, cfg.braking_max_speed)

    def _desired_terminal_vy(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_target_ratio * self._braking_speed_limit(alt, max_thrust_accel, max_tilt)
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap)
        return -max(cfg.braking_min_speed, vy_mag)

    def _descent_floor_vy(self, alt: float, max_thrust_accel: float, max_tilt: float) -> float:
        cfg = self._cfg
        vy_mag = cfg.braking_floor_ratio * self._braking_speed_limit(alt, max_thrust_accel, max_tilt)
        if alt <= cfg.vy_low_alt_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_low_alt_cap + 1.2)
        if alt <= cfg.vy_touch_cap_alt:
            vy_mag = min(vy_mag, cfg.vy_touch_cap + 0.3)
        return -max(cfg.braking_min_speed, vy_mag)

    def _resolve_max_tilt(
        self,
        alt: float,
        dx: float,
        vx: float,
        *,
        dy: float = 0.0,
        phase: str | None = None,
    ) -> float:
        cfg = self._cfg
        if alt < cfg.low_alt_tilt_alt:
            if abs(dx) <= cfg.low_alt_tilt_dx and abs(vx) <= cfg.low_alt_tilt_vx:
                tilt = cfg.max_tilt_low_alt
            else:
                tilt = cfg.max_tilt_low_alt_far
        else:
            tilt = cfg.max_tilt
        if (
            phase == "setup"
            and float(dy) >= cfg.uphill_setup_dy_min
            and alt <= cfg.uphill_setup_tilt_alt
        ):
            tilt = min(tilt, cfg.uphill_setup_tilt_max)
        return tilt

    def _phase_terminal_x_tol(self, phase: str) -> float:
        cfg = self._cfg
        ratio = cfg.terminal_center_tol_ratio
        if phase == "setup":
            ratio = cfg.setup_center_tol_ratio
        return max(4.0, float(self._last_target_half) * max(0.05, float(ratio)))

    def _shape_apex_target(self, dx_abs: float) -> float:
        cfg = self._cfg
        return clamp(
            float(cfg.setup_apex_height_per_dx) * max(0.0, float(dx_abs)),
            float(cfg.setup_apex_height_min),
            float(cfg.setup_apex_height_max),
        )

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
        cfg = self._cfg
        if phase == "setup":
            return clamp(float(cfg.setup_apex_ref_blend), 0.0, 1.0)
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
    ) -> PDGOptimizer:
        if phase == "setup":
            return self._optimizer_setup
        if phase == "terminal":
            return self._optimizer_terminal
        cfg = self._cfg
        down_speed = max(0.0, -float(vy_up))
        t_go = float("inf") if down_speed <= 1e-3 else (max(0.0, alt) / down_speed)
        if alt >= cfg.long_horizon_altitude or t_go >= cfg.long_horizon_time_to_go:
            return self._optimizer_setup
        return self._optimizer_terminal

    def _replan_policy_for_phase(self, phase: str) -> tuple[float, float, float, float, float]:
        cfg = self._cfg
        if phase == "setup":
            return (
                cfg.replan_hz_setup,
                cfg.replan_dx_error_setup,
                cfg.replan_dy_error_setup,
                cfg.replan_vx_error_setup,
                cfg.replan_vy_error_setup,
            )
        if phase == "terminal":
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
        )

    def _update_phase_tracking(
        self,
        *,
        passive: Sensors,
        dx: float,
        dy: float,
        alt: float,
        projection: BallisticProjection,
    ) -> None:
        _update_phase_tracking_impl(
            self,
            passive=passive,
            dx=dx,
            dy=dy,
            alt=alt,
            projection=projection,
        )

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
        den = self._shape_target_x - self._shape_start_x
        if abs(den) <= 1e-6:
            s = 0.0
        else:
            s = clamp((float(x) - self._shape_start_x) / den, 0.0, 1.0)
        baseline = ((1.0 - s) * self._shape_start_y) + (s * self._shape_target_y)
        return baseline + (4.0 * self._shape_apex_target_over_target * s * (1.0 - s))

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

    def _shape_curve_rmse(self) -> float | None:
        if self._shape_curve_count <= 0:
            return None
        return math.sqrt(self._shape_curve_sq_err_sum / max(1, self._shape_curve_count))

    def _shape_projected_dx_abs_mean(self) -> float | None:
        if self._shape_projected_dx_count <= 0:
            return None
        return self._shape_projected_dx_abs_sum / max(1, self._shape_projected_dx_count)

    def _shape_shortfall_ratio(self) -> float | None:
        if self._shape_shortfall_sample_count <= 0:
            return None
        return self._shape_shortfall_count / max(1, self._shape_shortfall_sample_count)

    def _finalize_terminal_gate(
        self,
        *,
        passive: Sensors,
        alt: float,
        projected_dx: float,
        mode: str,
        horizon_s: float,
        terminal_speed: float,
        peak_accel_ratio: float,
        od_excess_s: float,
        latest_safe_margin_s: float,
        required_accel_ratio: float,
    ) -> None:
        _finalize_terminal_gate_metrics_impl(
            self,
            passive=passive,
            alt=alt,
            projected_dx=projected_dx,
        )
        self._flare_gate_mode = mode
        self._flare_gate_horizon_s = horizon_s
        self._flare_gate_terminal_speed = terminal_speed
        self._flare_gate_peak_accel_ratio = peak_accel_ratio
        self._flare_gate_od_excess_s = od_excess_s
        self._flare_gate_latest_safe_margin_s = latest_safe_margin_s
        self._flare_gate_required_accel_ratio = required_accel_ratio

    def _evaluate_flare_gate(
        self,
        *,
        dt: float,
        passive: Sensors,
        dx: float,
        dy: float,
        alt: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
        nominal_thrust_accel: float,
        thrust_ramp_up: float,
    ):
        return _evaluate_flare_gate_impl(
            self,
            dt=dt,
            passive=passive,
            dx=dx,
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
            dy=dy,
            alt=alt,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            max_thrust_accel=max_thrust_accel,
        )

    def update(self, dt: float, passive: Sensors) -> BotAction:
        if passive.state == "crashed":
            return self._reset_with_status(
                angle=passive.angle,
                status="zem_zev crashed",
                mode="idle",
                phase="crashed",
                summary="crashed",
            )
        if passive.state == "out_of_fuel":
            return self._reset_with_status(
                angle=passive.angle,
                status="zem_zev out_of_fuel",
                mode="idle",
                phase="out_of_fuel",
                summary="out of fuel",
            )

        if passive.state == "landed":
            self._reset_state()

        max_power, min_throttle, max_throttle, ramp_up = engine_profile(self.vehicle_info)
        target = self._resolve_target_contact(passive)
        target_uid = target.uid if target is not None else None

        if passive.state == "landed":
            landed_uid = self._landed_contact_uid(passive)
            if target_uid is None or landed_uid == target_uid:
                self._launch_takeoff_active = False
                action = BotAction(0.0, 0.0, False, status="zem_zev landed")
                self._set_display_state(mode="idle", phase="landed", summary="landed")
                self.status = action.status
                return action

            self._launch_takeoff_active = True
            action = BotAction(
                self._takeoff_thrust(max_throttle),
                0.0,
                False,
                status="zem_zev takeoff",
            )
            self._set_display_state(mode="takeoff", phase="takeoff", summary="departing pad")
            self.status = action.status
            return action

        if passive.state != "flying":
            return self._reset_with_status(
                angle=passive.angle,
                status=f"zem_zev {passive.state}",
                mode="idle",
                phase=str(passive.state),
                summary=str(passive.state),
            )
        if (
            self._last_flight_snapshot is not None
            and self._elapsed_time_s <= 1e-9
            and self._solve_count == 0
        ):
            # New run after a reset: discard prior episode telemetry.
            self._last_flight_snapshot = None

        alt = max(0.0, finite_altitude(passive))
        if self._launch_takeoff_active and alt < self._cfg.launch_takeoff_clear_altitude:
            action = BotAction(
                self._takeoff_thrust(max_throttle),
                0.0,
                False,
                status="zem_zev clear_pad",
            )
            self._set_display_state(mode="takeoff", phase="takeoff", summary="clearing pad")
            self.status = action.status
            return action
        if self._launch_takeoff_active and alt >= self._cfg.launch_takeoff_clear_altitude:
            self._launch_takeoff_active = False

        if not self._angle_cmd_initialized:
            self._prev_angle_cmd = float(passive.angle)
            self._angle_cmd_initialized = True

        mass = max(0.5, float(passive.mass))
        max_force = max_power * max_throttle
        nominal_force = max_power * min(1.0, max_throttle)
        min_force = max_power * min_throttle
        max_thrust_accel = max(0.1, max_force / mass)
        nominal_thrust_accel = max(0.1, nominal_force / mass)
        min_thrust_accel = max(0.0, min_force / mass)

        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            self._last_target_half = target_half_width(getattr(target, "size", None))
            self._last_target_y = float(target.y)
            self._peak_alt_over_target = max(
                self._peak_alt_over_target,
                max(0.0, float(passive.y) - self._last_target_y),
            )
            self._clearance_margin = 0.0
            self._clearance_scale = 0.0
            self._clearance_active = False
        else:
            dx = 0.0
            dy = -max(0.0, finite_altitude(passive))
            self._last_target_y = 0.0
            self._clearance_margin = 0.0
            self._clearance_scale = 0.0
            self._clearance_active = False

        self._elapsed_time_s += max(0.0, float(dt))
        self._track_setup_phase_metrics(dt=dt, passive=passive)
        self._maybe_start_shape_window(passive=passive, dx=dx, dy=dy)
        projection = estimate_target_y_projection(
            dx=dx,
            dy=dy,
            vx=float(passive.vx),
            vy_up=float(passive.vy_up),
            x=float(passive.x),
            y=float(passive.y),
        )
        self._update_phase_tracking(
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
        if self._active_phase == "coast":
            flare_gate = self._evaluate_flare_gate(
                dt=dt,
                passive=passive,
                dx=dx,
                dy=dy,
                alt=alt,
                max_thrust_accel=max_thrust_accel,
                min_thrust_accel=min_thrust_accel,
                nominal_thrust_accel=nominal_thrust_accel,
                thrust_ramp_up=ramp_up,
            )
            if flare_gate is not None:
                probe = flare_gate.probe
                self._finalize_terminal_gate(
                    passive=passive,
                    alt=alt,
                    projected_dx=probe.terminal_dx,
                    mode=flare_gate.mode,
                    horizon_s=probe.horizon_s,
                    terminal_speed=probe.terminal_speed,
                    peak_accel_ratio=probe.peak_accel_ratio,
                    od_excess_s=probe.od_excess_s,
                    latest_safe_margin_s=flare_gate.latest_safe_margin_s,
                    required_accel_ratio=probe.required_accel_ratio,
                )
                self._active_phase = "terminal"
                self._plan = probe.plan
                self._plan_elapsed = 0.0
                self._replan_timer = 1.0 / max(1e-3, self._cfg.replan_hz_terminal)
                self._fallback_steps_remaining = int(self._cfg.fallback_hold_steps)
            else:
                self._plan = None
                self._plan_elapsed = 0.0
                self._replan_timer = 0.0
                self._fallback_steps_remaining = 0
                action = _command_passive_coast_impl(
                    self,
                    dt=dt,
                    passive=passive,
                )
                action.status = (
                    f"zem_zev passive/coast "
                    f"dx={stable(dx, 1):.1f} pdx={stable(float(projection.projected_dx), 1):.1f}"
                )
                self._set_display_state(
                    mode="passive",
                    phase="coast",
                    summary=(
                        f"dx={stable(dx, 1):.1f} "
                        f"pdx={stable(float(projection.projected_dx), 1):.1f}"
                    ),
                )
                self.status = action.status
                self._last_flight_snapshot = self._build_evaluation_snapshot()
                return action
        replan_hz, dx_err_lim, dy_err_lim, vx_err_lim, vy_err_lim = self._replan_policy_for_phase(
            self._active_phase
        )

        self._replan_timer -= max(0.0, dt)
        self._plan_elapsed += max(0.0, dt)

        need_replan = (
            self._plan is None
            or not self._plan.feasible
            or self._replan_timer <= 0.0
            or self._state_deviation_requires_replan(
                passive,
                dx_err_lim=dx_err_lim,
                dy_err_lim=dy_err_lim,
                vx_err_lim=vx_err_lim,
                vy_err_lim=vy_err_lim,
            )
        )

        if need_replan:
            plan = self._solve_plan(
                passive=passive,
                dx=dx,
                dy=dy,
                max_thrust_accel=max_thrust_accel,
                min_thrust_accel=min_thrust_accel,
                nominal_thrust_accel=nominal_thrust_accel,
                phase=self._active_phase,
            )
            if plan is not None and plan.feasible:
                self._plan = plan
                self._plan_elapsed = 0.0
                self._replan_timer = 1.0 / max(1e-3, replan_hz)
                self._fallback_steps_remaining = int(self._cfg.fallback_hold_steps)
            else:
                if self._fallback_steps_remaining > 0 and self._plan is not None and self._plan.feasible:
                    self._fallback_steps_remaining -= 1
                else:
                    self._plan = None

        action = self._command_from_plan(
            dt=dt,
            passive=passive,
            dx=dx,
            dy=dy,
            alt=alt,
            max_power=max_power,
            min_throttle=min_throttle,
            max_throttle=max_throttle,
            max_thrust_accel=max_thrust_accel,
        )

        phase = self._active_phase
        mode = "opt"
        if self._plan is None or not self._plan.feasible:
            mode = "fallback"
            self._fallback_frames += 1
        action.status = (
            f"zem_zev {mode}/{phase} "
            f"dx={stable(dx, 1):.1f} pdx={stable(float(projection.projected_dx), 1):.1f}"
        )
        self._set_display_state(
            mode=mode,
            phase=phase,
            summary=(
                f"dx={stable(dx, 1):.1f} "
                f"pdx={stable(float(projection.projected_dx), 1):.1f}"
            ),
        )
        self.status = action.status
        self._last_flight_snapshot = self._build_evaluation_snapshot()
        return action

    def _build_evaluation_snapshot(self) -> dict[str, float | int | bool | str | None]:
        return _build_evaluation_snapshot_impl(self)

    def get_bot_telemetry(self) -> dict[str, float | int | bool | str | None]:
        return _resolve_evaluation_snapshot_impl(self)

    def get_display_state(self) -> BotDisplayState | None:
        return BotDisplayState(
            bot_name="zem_zev",
            mode=self._display_mode,
            phase=self._display_phase or self._active_phase,
            summary=self._display_summary,
        )

    def get_flight_phase_snapshot(self) -> FlightPhaseSnapshot | None:
        milestones: tuple[str, ...] = ("setup_gate",) if self._setup_gate_done else ()
        setup_gate = None
        if self._setup_gate_done:
            setup_gate = SetupGateMetrics(
                time_s=self._setup_gate_time,
                altitude=self._setup_gate_altitude,
                x=self._setup_gate_x,
                y=self._setup_gate_y,
                vx=self._setup_gate_vx,
                vy_up=self._setup_gate_vy_up,
                projected_apex_y=self._setup_gate_projected_apex_y,
                projected_apex_over_target=self._setup_gate_projected_apex_over_target,
                has_target_y_solution=self._setup_gate_has_target_y_solution,
                projected_impact_dx=self._setup_gate_projected_impact_dx,
                projected_impact_angle_deg=self._setup_gate_projected_impact_angle_deg,
                burn_duration_s=self._setup_gate_burn_duration_s,
                burn_fuel_used=self._setup_gate_burn_fuel_used,
                burn_avg_thrust_level=self._setup_gate_burn_avg_thrust_level,
            )
        return FlightPhaseSnapshot(
            phase=self._active_phase,
            milestones=milestones,
            setup_gate=setup_gate,
        )

    def get_plot_markers(self) -> tuple[PlotMarker, ...]:
        out: list[PlotMarker] = []
        if self._setup_gate_done:
            out.append(
                PlotMarker(
                    id="setup_gate",
                    name="setup_gate",
                    label="setup gate",
                    x=self._setup_gate_x,
                    y=self._setup_gate_y,
                    metadata={
                        "time_s": self._setup_gate_time,
                        "vx": self._setup_gate_vx,
                        "vy_up": self._setup_gate_vy_up,
                    },
                )
            )
        if self._terminal_gate_done:
            label = "flare"
            if self._flare_gate_mode:
                mode_label = "green" if self._flare_gate_mode == "green_exact" else "amber"
                label = f"{label} {mode_label}"
            if self._terminal_gate_projected_dx is not None:
                label = f"{label} dx={stable(self._terminal_gate_projected_dx, 1):.1f}"
            metadata: dict[str, float | str | None] = {"time_s": self._terminal_gate_time}
            if self._flare_gate_mode is not None:
                metadata["mode"] = self._flare_gate_mode
            if self._flare_gate_horizon_s is not None:
                metadata["horizon_s"] = self._flare_gate_horizon_s
            out.append(
                PlotMarker(
                    id="terminal_entry",
                    name="terminal_entry",
                    label=label,
                    x=self._terminal_gate_x,
                    y=self._terminal_gate_y,
                    metadata=metadata,
                )
            )
        return tuple(out)

    def get_evaluation_decision(self) -> BotEvalDecision | None:
        return _build_evaluation_decision_impl(self)

def create_bot() -> Bot:
    return ZemZevBot()

def list_behavior_names() -> tuple[str, ...]:
    return ("zem_zev",)


__all__ = ["ZemZevBot", "create_bot", "list_behavior_names"]
