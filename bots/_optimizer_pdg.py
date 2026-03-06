"""Optimizer-first powered descent guidance helpers.

This module provides a small receding-horizon trajectory optimizer used by
`zem_zev`. It keeps the formulation convex (QP/SOCP) so solves are robust and
warm-start friendly at runtime.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cvxpy as cp
import numpy as np


@dataclass(frozen=True)
class PDGOptimizerConfig:
    horizon_steps: int = 36
    step_dt: float = 0.20
    solver: str = "CLARABEL"
    solver_max_iters: int = 140

    # Objective shaping
    w_terminal_x: float = 26.0
    w_terminal_y: float = 34.0
    w_terminal_vx: float = 15.0
    w_terminal_vy: float = 3.0
    w_projected_dx_terminal: float = 220.0
    w_projected_dx_tail: float = 70.0
    projected_dx_tail_ratio: float = 0.55
    w_apex_shortfall: float = 95.0
    w_apex_overshoot: float = 120.0
    w_apex_upward_vy: float = 40.0
    apex_index_ratio: float = 0.45
    # End-of-horizon setup-goal slacks (keep zero to disable).
    w_goal_projected_dx_slack: float = 0.0
    w_goal_apex_y_slack: float = 0.0
    w_goal_apex_vy_slack: float = 0.0
    w_burn_hold: float = 12.0
    burn_hold_ratio: float = 0.60
    burn_hold_floor_ratio: float = 0.36
    w_burn_drop: float = 8.0
    w_burn_tail: float = 2.0
    burn_tail_ratio: float = 0.30
    w_effort: float = 0.020
    w_smooth: float = 0.12
    w_path_x: float = 0.030
    w_path_y: float = 0.015
    w_path_vx: float = 0.0
    w_path_vy: float = 0.0
    w_upward_vy: float = 1.20

    # Soft floor around minimum thrust acceleration (convex hinge penalty)
    w_min_accel: float = 0.18
    w_descent_floor: float = 0.24
    w_altitude_progress: float = 0.00
    w_downspeed_progress: float = 0.00
    w_thrust_linear: float = 0.14
    w_overdrive_linear: float = 1.40
    w_overdrive_quadratic: float = 6.00
    tilt_relax_accel: float = 0.0

    # Altitude-adaptive reference profile (lateral-first then descend).
    ref_hold_frac_min: float = 0.0
    ref_hold_frac_max: float = 0.0
    ref_altitude_scale: float = 420.0
    ref_hold_descent_ratio: float = 0.55


@dataclass(frozen=True)
class PDGPlan:
    feasible: bool
    status: str
    solve_time_ms: float
    objective: float
    step_dt: float
    ax: tuple[float, ...]
    ay: tuple[float, ...]
    x: tuple[float, ...]
    y: tuple[float, ...]
    vx: tuple[float, ...]
    vy: tuple[float, ...]

    def shifted(self) -> "PDGPlan":
        """Return a one-step-shifted copy for warm-starting the next solve."""
        if len(self.ax) <= 1:
            return self

        def _shift(seq: tuple[float, ...]) -> tuple[float, ...]:
            return tuple(seq[1:]) + (seq[-1],)

        def _shift_state(seq: tuple[float, ...]) -> tuple[float, ...]:
            return tuple(seq[1:]) + (seq[-1],)

        return PDGPlan(
            feasible=self.feasible,
            status=self.status,
            solve_time_ms=self.solve_time_ms,
            objective=self.objective,
            step_dt=self.step_dt,
            ax=_shift(self.ax),
            ay=_shift(self.ay),
            x=_shift_state(self.x),
            y=_shift_state(self.y),
            vx=_shift_state(self.vx),
            vy=_shift_state(self.vy),
        )


class PDGOptimizer:
    """Small convex powered-descent optimizer with reusable problem graph."""

    def __init__(self, cfg: PDGOptimizerConfig | None = None) -> None:
        self._cfg = cfg or PDGOptimizerConfig()
        self._problem: cp.Problem | None = None

        self._x: cp.Variable | None = None
        self._y: cp.Variable | None = None
        self._vx: cp.Variable | None = None
        self._vy: cp.Variable | None = None
        self._ax: cp.Variable | None = None
        self._ay: cp.Variable | None = None

        self._x0: cp.Parameter | None = None
        self._y0: cp.Parameter | None = None
        self._vx0: cp.Parameter | None = None
        self._vy0: cp.Parameter | None = None
        self._target_x: cp.Parameter | None = None
        self._target_y: cp.Parameter | None = None
        self._y_floor: cp.Parameter | None = None
        self._target_vy: cp.Parameter | None = None
        self._a_max: cp.Parameter | None = None
        self._a_min: cp.Parameter | None = None
        self._a_nom: cp.Parameter | None = None
        self._tilt_tan: cp.Parameter | None = None
        self._x_ref: cp.Parameter | None = None
        self._y_ref: cp.Parameter | None = None
        self._vy_floor: cp.Parameter | None = None
        self._g_param: cp.Parameter | None = None
        self._x_tol: cp.Parameter | None = None
        self._proj_t_fall: cp.Parameter | None = None
        self._apex_target_y: cp.Parameter | None = None
        self._goal_projected_dx_tol: cp.Parameter | None = None
        self._goal_apex_y_tol: cp.Parameter | None = None
        self._goal_apex_vy_target: cp.Parameter | None = None
        self._goal_apex_vy_tol: cp.Parameter | None = None

        self._build_problem()

    @property
    def horizon_steps(self) -> int:
        return int(self._cfg.horizon_steps)

    @property
    def step_dt(self) -> float:
        return float(self._cfg.step_dt)

    def _reference_profiles(
        self,
        *,
        x: float,
        y: float,
        target_x: float,
        target_y: float,
        altitude_hint: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        cfg = self._cfg
        n = int(cfg.horizon_steps)
        x_ref = np.linspace(float(x), float(target_x), n + 1)
        if cfg.ref_hold_frac_max <= 1e-6:
            return x_ref, np.linspace(float(y), float(target_y), n + 1)

        if n <= 1:
            y_ref = np.linspace(float(y), float(target_y), n + 1)
            return x_ref, y_ref

        alt_alpha = np.clip(float(altitude_hint) / max(1e-6, cfg.ref_altitude_scale), 0.0, 1.0)
        hold_frac = float(
            cfg.ref_hold_frac_min
            + ((cfg.ref_hold_frac_max - cfg.ref_hold_frac_min) * alt_alpha)
        )
        hold_steps = int(np.clip(round(hold_frac * n), 1, n - 1))

        y_start = float(y)
        y_goal = float(target_y)
        y_hold = y_start + ((y_goal - y_start) * float(cfg.ref_hold_descent_ratio))

        y_ref = np.empty(n + 1, dtype=float)
        y_ref[: hold_steps + 1] = np.linspace(y_start, y_hold, hold_steps + 1)
        y_ref[hold_steps:] = np.linspace(y_hold, y_goal, (n - hold_steps) + 1)
        return x_ref, y_ref

    def _build_problem(self) -> None:
        cfg = self._cfg
        n = int(cfg.horizon_steps)
        dt = float(cfg.step_dt)
        dt2 = dt * dt
        g_param = cp.Parameter(nonneg=True)

        x = cp.Variable(n + 1)
        y = cp.Variable(n + 1)
        vx = cp.Variable(n + 1)
        vy = cp.Variable(n + 1)
        ax = cp.Variable(n)
        ay = cp.Variable(n)

        x0 = cp.Parameter()
        y0 = cp.Parameter()
        vx0 = cp.Parameter()
        vy0 = cp.Parameter()
        target_x = cp.Parameter()
        target_y = cp.Parameter()
        y_floor = cp.Parameter(n + 1)
        target_vy = cp.Parameter()
        a_max = cp.Parameter(nonneg=True)
        a_min = cp.Parameter(nonneg=True)
        a_nom = cp.Parameter(nonneg=True)
        tilt_tan = cp.Parameter(nonneg=True)
        x_ref = cp.Parameter(n + 1)
        y_ref = cp.Parameter(n + 1)
        vy_floor = cp.Parameter()
        x_tol = cp.Parameter(nonneg=True)
        proj_t_fall = cp.Parameter(nonneg=True)
        apex_target_y = cp.Parameter()
        goal_projected_dx_tol = cp.Parameter(nonneg=True)
        goal_apex_y_tol = cp.Parameter(nonneg=True)
        goal_apex_vy_target = cp.Parameter()
        goal_apex_vy_tol = cp.Parameter(nonneg=True)
        thrust_norm = cp.Variable(n, nonneg=True)
        od_slack = cp.Variable(n, nonneg=True)
        goal_projected_dx_slack = cp.Variable(nonneg=True)
        goal_apex_y_slack = cp.Variable(nonneg=True)
        goal_apex_vy_slack = cp.Variable(nonneg=True)

        constraints: list[cp.Expression] = [
            x[0] == x0,
            y[0] == y0,
            vx[0] == vx0,
            vy[0] == vy0,
            y >= y_floor,
        ]
        tilt_relax_accel = max(0.0, float(cfg.tilt_relax_accel))

        for k in range(n):
            constraints.extend(
                [
                    x[k + 1] == x[k] + (vx[k] * dt) + (0.5 * ax[k] * dt2),
                    # Gravity comes from runtime config, not a hardcoded Earth value.
                    y[k + 1] == y[k] + (vy[k] * dt) + (0.5 * (ay[k] - g_param) * dt2),
                    vx[k + 1] == vx[k] + (ax[k] * dt),
                    vy[k + 1] == vy[k] + ((ay[k] - g_param) * dt),
                    ay[k] >= 0.0,
                    cp.norm(cp.hstack([ax[k], ay[k]]), 2) <= a_max,
                    cp.abs(ax[k]) <= tilt_tan * (ay[k] + tilt_relax_accel),
                    thrust_norm[k] >= cp.norm(cp.hstack([ax[k], ay[k]]), 2),
                    thrust_norm[k] <= a_nom + od_slack[k],
                    od_slack[k] <= (a_max - a_nom),
                ]
            )

        effort = cp.sum_squares(ax) + cp.sum_squares(ay)
        smooth = cp.sum_squares(ax[1:] - ax[:-1]) + cp.sum_squares(ay[1:] - ay[:-1])
        x_ref_v = (x_ref[1:] - x_ref[:-1]) / dt
        y_ref_v = (y_ref[1:] - y_ref[:-1]) / dt
        path_vx = cp.sum_squares(vx[:-1] - x_ref_v)
        path_vy = cp.sum_squares(vy[:-1] - y_ref_v)
        upward_penalty = cp.sum_squares(cp.pos(vy[:-1]))
        descent_floor_penalty = cp.sum_squares(cp.pos(vy[:-1] - vy_floor))
        min_accel_soft = cp.sum_squares(cp.pos(a_min - ay))
        projected_dx = (x - target_x) + (vx * proj_t_fall)
        tail_start = int(np.clip(round(cfg.projected_dx_tail_ratio * n), 0, n))
        apex_idx = int(np.clip(round(cfg.apex_index_ratio * n), 0, n))
        hold_steps = int(np.clip(round(cfg.burn_hold_ratio * n), 1, n))
        tail_steps = int(np.clip(round(cfg.burn_tail_ratio * n), 1, n))
        tail_idx = max(0, n - tail_steps)
        hold_floor = max(0.0, float(cfg.burn_hold_floor_ratio)) * a_nom

        projected_dx_terminal = cp.square(projected_dx[n])
        projected_dx_tail = cp.sum_squares(projected_dx[tail_start:])
        apex_shortfall = cp.square(cp.pos(apex_target_y - y[apex_idx]))
        apex_overshoot = cp.sum_squares(cp.pos(y[apex_idx:] - apex_target_y))
        apex_upward_vy = cp.sum_squares(cp.pos(vy[apex_idx:]))
        constraints.extend(
            [
                cp.abs(projected_dx[n]) <= goal_projected_dx_tol + goal_projected_dx_slack,
                cp.abs(y[n] - apex_target_y) <= goal_apex_y_tol + goal_apex_y_slack,
                cp.abs(vy[n] - goal_apex_vy_target) <= goal_apex_vy_tol + goal_apex_vy_slack,
            ]
        )
        burn_hold = cp.sum_squares(cp.pos(hold_floor - thrust_norm[:hold_steps]))
        if hold_steps > 1:
            burn_drop = cp.sum_squares(
                cp.pos(thrust_norm[: hold_steps - 1] - thrust_norm[1:hold_steps])
            )
        else:
            burn_drop = cp.Constant(0.0)
        burn_tail = cp.sum_squares(thrust_norm[tail_idx:])

        terminal = (
            # Penalize only outside the pad corridor to avoid over-centering waste.
            cfg.w_terminal_x * cp.square(cp.pos(cp.abs(x[n] - target_x) - x_tol))
            + cfg.w_terminal_y * cp.square(y[n] - target_y)
            + cfg.w_terminal_vx * cp.square(vx[n])
            + cfg.w_terminal_vy * cp.square(vy[n] - target_vy)
        )
        goal_projected_dx = cp.square(goal_projected_dx_slack)
        goal_apex_y = cp.square(goal_apex_y_slack)
        goal_apex_vy = cp.square(goal_apex_vy_slack)

        objective = cp.Minimize(
            terminal
            + (cfg.w_effort * effort)
            + (cfg.w_smooth * smooth)
            + (cfg.w_path_x * cp.sum_squares(x - x_ref))
            + (cfg.w_path_y * cp.sum_squares(y - y_ref))
            + (cfg.w_path_vx * path_vx)
            + (cfg.w_path_vy * path_vy)
            + (cfg.w_upward_vy * upward_penalty)
            + (cfg.w_descent_floor * descent_floor_penalty)
            + (cfg.w_min_accel * min_accel_soft)
            + (cfg.w_projected_dx_terminal * projected_dx_terminal)
            + (cfg.w_projected_dx_tail * projected_dx_tail)
            + (cfg.w_apex_shortfall * apex_shortfall)
            + (cfg.w_apex_overshoot * apex_overshoot)
            + (cfg.w_apex_upward_vy * apex_upward_vy)
            + (cfg.w_goal_projected_dx_slack * goal_projected_dx)
            + (cfg.w_goal_apex_y_slack * goal_apex_y)
            + (cfg.w_goal_apex_vy_slack * goal_apex_vy)
            + (cfg.w_burn_hold * burn_hold)
            + (cfg.w_burn_drop * burn_drop)
            + (cfg.w_burn_tail * burn_tail)
            + (cfg.w_thrust_linear * cp.sum(thrust_norm))
            + (cfg.w_overdrive_linear * cp.sum(od_slack))
            + (cfg.w_overdrive_quadratic * cp.sum_squares(od_slack))
        )

        self._problem = cp.Problem(objective, constraints)

        self._x = x
        self._y = y
        self._vx = vx
        self._vy = vy
        self._ax = ax
        self._ay = ay

        self._x0 = x0
        self._y0 = y0
        self._vx0 = vx0
        self._vy0 = vy0
        self._target_x = target_x
        self._target_y = target_y
        self._y_floor = y_floor
        self._target_vy = target_vy
        self._a_max = a_max
        self._a_min = a_min
        self._a_nom = a_nom
        self._tilt_tan = tilt_tan
        self._x_ref = x_ref
        self._y_ref = y_ref
        self._vy_floor = vy_floor
        self._g_param = g_param
        self._x_tol = x_tol
        self._proj_t_fall = proj_t_fall
        self._apex_target_y = apex_target_y
        self._goal_projected_dx_tol = goal_projected_dx_tol
        self._goal_apex_y_tol = goal_apex_y_tol
        self._goal_apex_vy_target = goal_apex_vy_target
        self._goal_apex_vy_tol = goal_apex_vy_tol

    def solve(
        self,
        *,
        x: float,
        y: float,
        vx: float,
        vy: float,
        target_x: float,
        target_y: float,
        y_floor: float | tuple[float, float] | list[float],
        target_vy: float,
        max_thrust_accel: float,
        min_thrust_accel: float,
        nominal_thrust_accel: float,
        max_tilt_rad: float,
        descent_floor_vy: float,
        gravity_mag: float,
        pad_half_width: float,
        altitude_hint: float,
        warm_start: PDGPlan | None,
        projected_t_fall: float | None = None,
        apex_target_y: float | None = None,
        goal_projected_dx_tol: float | None = None,
        goal_apex_y_tol: float | None = None,
        goal_apex_vy_target: float | None = None,
        goal_apex_vy_tol: float | None = None,
        terminal_x_tol: float | None = None,
        y_ref_override: list[float] | tuple[float, ...] | np.ndarray | None = None,
    ) -> PDGPlan | None:
        if self._problem is None:
            return None

        n = int(self._cfg.horizon_steps)

        self._x0.value = float(x)
        self._y0.value = float(y)
        self._vx0.value = float(vx)
        self._vy0.value = float(vy)
        self._target_x.value = float(target_x)
        self._target_y.value = float(target_y)
        if isinstance(y_floor, (int, float)):
            y_floor_profile = np.full(n + 1, float(y_floor), dtype=float)
        elif len(y_floor) == 2:
            y_floor_profile = np.linspace(float(y_floor[0]), float(y_floor[1]), n + 1)
        else:
            y_floor_profile = np.asarray(y_floor, dtype=float)
            if y_floor_profile.shape != (n + 1,):
                raise ValueError(
                    f"y_floor profile must have {n + 1} elements, got {y_floor_profile.shape}"
                )
        self._y_floor.value = y_floor_profile
        self._target_vy.value = float(target_vy)
        self._a_max.value = max(0.1, float(max_thrust_accel))
        self._a_min.value = max(0.0, float(min_thrust_accel))
        self._a_nom.value = min(
            max(0.1, float(max_thrust_accel)),
            max(0.1, float(nominal_thrust_accel)),
        )
        self._tilt_tan.value = max(1e-3, math.tan(max(0.02, float(max_tilt_rad))))
        self._vy_floor.value = float(descent_floor_vy)
        self._g_param.value = max(0.0, float(gravity_mag))
        if projected_t_fall is None:
            fallback_t = max(
                0.5,
                max(0.0, float(altitude_hint))
                / max(1.0, max(0.0, -float(vy)) + 1.0),
            )
            self._proj_t_fall.value = fallback_t
        else:
            self._proj_t_fall.value = max(0.25, float(projected_t_fall))
        self._apex_target_y.value = float(target_y if apex_target_y is None else apex_target_y)
        self._goal_projected_dx_tol.value = max(
            0.0,
            float(pad_half_width if goal_projected_dx_tol is None else goal_projected_dx_tol),
        )
        self._goal_apex_y_tol.value = max(
            0.0,
            float(35.0 if goal_apex_y_tol is None else goal_apex_y_tol),
        )
        self._goal_apex_vy_target.value = float(
            0.0 if goal_apex_vy_target is None else goal_apex_vy_target
        )
        self._goal_apex_vy_tol.value = max(
            0.0,
            float(3.5 if goal_apex_vy_tol is None else goal_apex_vy_tol),
        )
        x_tol = float(pad_half_width) if terminal_x_tol is None else float(terminal_x_tol)
        self._x_tol.value = max(0.0, x_tol)

        x_ref, y_ref_default = self._reference_profiles(
            x=float(x),
            y=float(y),
            target_x=float(target_x),
            target_y=float(target_y),
            altitude_hint=max(0.0, float(altitude_hint)),
        )
        if y_ref_override is None:
            y_ref = y_ref_default
        else:
            y_ref = np.asarray(y_ref_override, dtype=float)
            if y_ref.shape != (n + 1,):
                raise ValueError(
                    f"y_ref_override must have {n + 1} elements, got {y_ref.shape}"
                )
        self._x_ref.value = x_ref
        self._y_ref.value = y_ref

        if warm_start is not None and warm_start.feasible:
            shifted = warm_start.shifted()
            if len(shifted.ax) == n:
                self._ax.value = np.asarray(shifted.ax, dtype=float)
                self._ay.value = np.asarray(shifted.ay, dtype=float)
            if len(shifted.x) == n + 1:
                self._x.value = np.asarray(shifted.x, dtype=float)
                self._y.value = np.asarray(shifted.y, dtype=float)
                self._vx.value = np.asarray(shifted.vx, dtype=float)
                self._vy.value = np.asarray(shifted.vy, dtype=float)

        t0 = time.perf_counter()
        status = "error"
        try:
            self._problem.solve(
                solver=self._cfg.solver,
                warm_start=True,
                verbose=False,
                max_iter=self._cfg.solver_max_iters,
            )
            status = str(self._problem.status)
        except Exception:
            try:
                self._problem.solve(
                    solver="SCS",
                    warm_start=True,
                    verbose=False,
                    max_iters=250,
                )
                status = str(self._problem.status)
            except Exception:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                return PDGPlan(
                    feasible=False,
                    status="solve_error",
                    solve_time_ms=dt_ms,
                    objective=float("inf"),
                    step_dt=float(self._cfg.step_dt),
                    ax=tuple(0.0 for _ in range(n)),
                    ay=tuple(0.0 for _ in range(n)),
                    x=tuple(float(x) for _ in range(n + 1)),
                    y=tuple(float(y) for _ in range(n + 1)),
                    vx=tuple(float(vx) for _ in range(n + 1)),
                    vy=tuple(float(vy) for _ in range(n + 1)),
                )

        dt_ms = (time.perf_counter() - t0) * 1000.0
        feasible = status in {"optimal", "optimal_inaccurate"}
        if not feasible:
            return PDGPlan(
                feasible=False,
                status=status,
                solve_time_ms=dt_ms,
                objective=float("inf"),
                step_dt=float(self._cfg.step_dt),
                ax=tuple(0.0 for _ in range(n)),
                ay=tuple(0.0 for _ in range(n)),
                x=tuple(float(x) for _ in range(n + 1)),
                y=tuple(float(y) for _ in range(n + 1)),
                vx=tuple(float(vx) for _ in range(n + 1)),
                vy=tuple(float(vy) for _ in range(n + 1)),
            )

        ax_val = np.asarray(self._ax.value, dtype=float)
        ay_val = np.asarray(self._ay.value, dtype=float)
        x_val = np.asarray(self._x.value, dtype=float)
        y_val = np.asarray(self._y.value, dtype=float)
        vx_val = np.asarray(self._vx.value, dtype=float)
        vy_val = np.asarray(self._vy.value, dtype=float)

        objective = self._problem.value
        obj_val = float(objective) if objective is not None and math.isfinite(float(objective)) else 0.0

        return PDGPlan(
            feasible=True,
            status=status,
            solve_time_ms=dt_ms,
            objective=obj_val,
            step_dt=float(self._cfg.step_dt),
            ax=tuple(float(v) for v in ax_val),
            ay=tuple(float(v) for v in ay_val),
            x=tuple(float(v) for v in x_val),
            y=tuple(float(v) for v in y_val),
            vx=tuple(float(v) for v in vx_val),
            vy=tuple(float(v) for v in vy_val),
        )


__all__ = ["PDGOptimizerConfig", "PDGPlan", "PDGOptimizer"]
