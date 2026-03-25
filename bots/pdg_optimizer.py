"""Optimizer-first powered descent guidance helpers.

This module provides a small receding-horizon trajectory optimizer used by
`pdg`. It keeps the formulation convex (QP/SOCP) so solves are robust and
warm-start friendly at runtime.
"""

from __future__ import annotations

import importlib
import math
import time
from dataclasses import dataclass
from typing import Any

cp = importlib.import_module("cvxpy")
np = importlib.import_module("numpy")


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
    w_effort: float = 0.020
    w_smooth: float = 0.12
    w_path_x: float = 0.030
    w_path_y: float = 0.015
    w_upward_vy: float = 1.20

    # Soft floor around minimum thrust acceleration (convex hinge penalty)
    w_min_accel: float = 0.18
    w_descent_floor: float = 0.24
    w_altitude_progress: float = 0.00
    w_downspeed_progress: float = 0.00
    w_thrust_linear: float = 0.14
    w_overdrive_linear: float = 1.40
    w_overdrive_quadratic: float = 6.00
    w_boost_projected_dx: float = 60.0
    w_boost_target_y_cross: float = 55.0
    w_boost_apex: float = 26.0
    w_boost_angle: float = 22.0
    w_late_thrust: float = 0.0
    boost_angle_slope_target: float = 0.0

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
        self._problem: Any | None = None

        self._x: Any | None = None
        self._y: Any | None = None
        self._vx: Any | None = None
        self._vy: Any | None = None
        self._ax: Any | None = None
        self._ay: Any | None = None

        self._x0: Any | None = None
        self._y0: Any | None = None
        self._vx0: Any | None = None
        self._vy0: Any | None = None
        self._target_x: Any | None = None
        self._target_y: Any | None = None
        self._y_floor: Any | None = None
        self._target_vy: Any | None = None
        self._a_max: Any | None = None
        self._a_min: Any | None = None
        self._a_nom: Any | None = None
        self._tilt_tan: Any | None = None
        self._x_ref: Any | None = None
        self._y_ref: Any | None = None
        self._vy_floor: Any | None = None
        self._g_param: Any | None = None
        self._x_tol: Any | None = None
        self._boost_pdx_time_ref: Any | None = None
        self._boost_proj_target: Any | None = None
        self._boost_proj_x_scale: Any | None = None
        self._boost_proj_vx_scale: Any | None = None
        self._boost_cross_y_scale: Any | None = None
        self._boost_cross_vy_scale: Any | None = None
        self._boost_cross_target: Any | None = None
        self._boost_cross_drop_weighted: Any | None = None
        self._boost_angle_vx_scale: Any | None = None
        self._boost_angle_vy_scale: Any | None = None
        self._boost_angle_vy_bias: Any | None = None
        self._boost_descend_vy_scale: Any | None = None
        self._boost_descend_vy_bias: Any | None = None
        self._boost_no_away_dir: Any | None = None

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
    ) -> tuple[Any, Any]:
        cfg = self._cfg
        n = int(cfg.horizon_steps)
        x_ref = np.linspace(float(x), float(target_x), n + 1)
        if cfg.ref_hold_frac_max <= 1e-6:
            return x_ref, np.linspace(float(y), float(target_y), n + 1)

        if n <= 1:
            y_ref = np.linspace(float(y), float(target_y), n + 1)
            return x_ref, y_ref

        alt_alpha = np.clip(
            float(altitude_hint) / max(1e-6, cfg.ref_altitude_scale), 0.0, 1.0
        )
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
        boost_pdx_time_ref = cp.Parameter(n + 1, nonneg=True)
        boost_proj_target = cp.Parameter(n + 1)
        boost_proj_x_scale = cp.Parameter(n + 1, nonneg=True)
        boost_proj_vx_scale = cp.Parameter(n + 1)
        boost_cross_y_scale = cp.Parameter(n + 1, nonneg=True)
        boost_cross_vy_scale = cp.Parameter(n + 1)
        boost_cross_target = cp.Parameter(n + 1)
        boost_cross_drop_weighted = cp.Parameter(n + 1)
        boost_angle_vx_scale = cp.Parameter(n + 1, nonneg=True)
        boost_angle_vy_scale = cp.Parameter(n + 1, nonneg=True)
        boost_angle_vy_bias = cp.Parameter(n + 1)
        boost_descend_vy_scale = cp.Parameter(n + 1, nonneg=True)
        boost_descend_vy_bias = cp.Parameter(n + 1)
        boost_no_away_dir = cp.Parameter()
        thrust_norm = cp.Variable(n, nonneg=True)
        od_slack = cp.Variable(n, nonneg=True)
        boost_projected_dx_proxy = cp.Variable(n + 1)
        late_ramp = np.linspace(0.0, 1.0, n, dtype=float)

        constraints: list[Any] = [
            x[0] == x0,
            y[0] == y0,
            vx[0] == vx0,
            vy[0] == vy0,
            y >= y_floor,
        ]

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
                    cp.abs(ax[k]) <= tilt_tan * ay[k],
                    thrust_norm[k] >= cp.norm(cp.hstack([ax[k], ay[k]]), 2),
                    thrust_norm[k] <= a_nom + od_slack[k],
                    od_slack[k] <= (a_max - a_nom),
                    boost_no_away_dir * ax[k] >= 0.0,
                ]
            )
        constraints.extend(
            [
                boost_projected_dx_proxy
                == target_x - x - cp.multiply(boost_pdx_time_ref, vx),
            ]
        )
        for k in range(1, n + 1):
            constraints.append(boost_no_away_dir * boost_projected_dx_proxy[k] >= 0.0)

        effort = cp.sum_squares(ax) + cp.sum_squares(ay)
        smooth = cp.sum_squares(ax[1:] - ax[:-1]) + cp.sum_squares(ay[1:] - ay[:-1])
        path = cp.sum_squares(x - x_ref) + cp.sum_squares(y - y_ref)
        upward_penalty = cp.sum_squares(cp.pos(vy[:-1]))
        descent_floor_penalty = cp.sum_squares(cp.pos(vy[:-1] - vy_floor))
        min_accel_soft = cp.sum_squares(cp.pos(a_min - ay))
        late_thrust = cp.sum(cp.multiply(late_ramp, thrust_norm))

        terminal = (
            # Penalize only outside the pad corridor to avoid over-centering waste.
            cfg.w_terminal_x * cp.square(cp.pos(cp.abs(x[n] - target_x) - x_tol))
            + cfg.w_terminal_y * cp.square(y[n] - target_y)
            + cfg.w_terminal_vx * cp.square(vx[n])
            + cfg.w_terminal_vy * cp.square(vy[n] - target_vy)
        )

        objective_expr = (
            terminal
            + (cfg.w_effort * effort)
            + (cfg.w_smooth * smooth)
            + (cfg.w_path_x * cp.sum_squares(x - x_ref))
            + (cfg.w_path_y * cp.sum_squares(y - y_ref))
            + (cfg.w_upward_vy * upward_penalty)
            + (cfg.w_descent_floor * descent_floor_penalty)
            + (cfg.w_min_accel * min_accel_soft)
            + (0.02 * path)
            + (cfg.w_altitude_progress * cp.sum(y[:-1] - target_y))
            + (cfg.w_downspeed_progress * cp.sum(vy[:-1]))
            + (cfg.w_thrust_linear * cp.sum(thrust_norm))
            + (cfg.w_late_thrust * late_thrust)
            + (cfg.w_overdrive_linear * cp.sum(od_slack))
            + (cfg.w_overdrive_quadratic * cp.sum_squares(od_slack))
        )
        if (
            cfg.w_boost_projected_dx > 0.0
            or cfg.w_boost_target_y_cross > 0.0
            or cfg.w_boost_apex > 0.0
            or cfg.w_boost_angle > 0.0
        ):
            weighted_projected_dx = (
                boost_proj_target
                - cp.multiply(boost_proj_x_scale, x)
                - cp.multiply(boost_proj_vx_scale, vx)
            )
            weighted_y_cross = (
                cp.multiply(boost_cross_y_scale, y)
                + cp.multiply(boost_cross_vy_scale, vy)
                - boost_cross_drop_weighted
                - boost_cross_target
            )
            weighted_angle_shallow = (
                cp.multiply(boost_angle_vx_scale, cp.abs(vx))
                + cp.multiply(boost_angle_vy_scale, vy)
                - boost_angle_vy_bias
            )
            weighted_descend_guard = (
                cp.multiply(boost_descend_vy_scale, vy) - boost_descend_vy_bias
            )
            objective_expr = (
                objective_expr
                + (cfg.w_boost_projected_dx * cp.sum_squares(weighted_projected_dx))
                + (
                    cfg.w_boost_target_y_cross
                    * cp.sum_squares(cp.pos(-weighted_y_cross))
                )
                + (cfg.w_boost_apex * cp.sum_squares(cp.pos(weighted_y_cross)))
                + (
                    cfg.w_boost_angle
                    * (
                        cp.sum_squares(cp.pos(weighted_angle_shallow))
                        + cp.sum_squares(cp.pos(weighted_descend_guard))
                    )
                )
            )
        objective = cp.Minimize(objective_expr)

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
        self._boost_pdx_time_ref = boost_pdx_time_ref
        self._boost_proj_target = boost_proj_target
        self._boost_proj_x_scale = boost_proj_x_scale
        self._boost_proj_vx_scale = boost_proj_vx_scale
        self._boost_cross_y_scale = boost_cross_y_scale
        self._boost_cross_vy_scale = boost_cross_vy_scale
        self._boost_cross_target = boost_cross_target
        self._boost_cross_drop_weighted = boost_cross_drop_weighted
        self._boost_angle_vx_scale = boost_angle_vx_scale
        self._boost_angle_vy_scale = boost_angle_vy_scale
        self._boost_angle_vy_bias = boost_angle_vy_bias
        self._boost_descend_vy_scale = boost_descend_vy_scale
        self._boost_descend_vy_bias = boost_descend_vy_bias
        self._boost_no_away_dir = boost_no_away_dir

    def _require_solver_state(self) -> dict[str, Any]:
        required = {
            "problem": self._problem,
            "x": self._x,
            "y": self._y,
            "vx": self._vx,
            "vy": self._vy,
            "ax": self._ax,
            "ay": self._ay,
            "x0": self._x0,
            "y0": self._y0,
            "vx0": self._vx0,
            "vy0": self._vy0,
            "target_x": self._target_x,
            "target_y": self._target_y,
            "y_floor": self._y_floor,
            "target_vy": self._target_vy,
            "a_max": self._a_max,
            "a_min": self._a_min,
            "a_nom": self._a_nom,
            "tilt_tan": self._tilt_tan,
            "x_ref": self._x_ref,
            "y_ref": self._y_ref,
            "vy_floor": self._vy_floor,
            "g_param": self._g_param,
            "x_tol": self._x_tol,
            "boost_pdx_time_ref": self._boost_pdx_time_ref,
            "boost_proj_target": self._boost_proj_target,
            "boost_proj_x_scale": self._boost_proj_x_scale,
            "boost_proj_vx_scale": self._boost_proj_vx_scale,
            "boost_cross_y_scale": self._boost_cross_y_scale,
            "boost_cross_vy_scale": self._boost_cross_vy_scale,
            "boost_cross_target": self._boost_cross_target,
            "boost_cross_drop_weighted": self._boost_cross_drop_weighted,
            "boost_angle_vx_scale": self._boost_angle_vx_scale,
            "boost_angle_vy_scale": self._boost_angle_vy_scale,
            "boost_angle_vy_bias": self._boost_angle_vy_bias,
            "boost_descend_vy_scale": self._boost_descend_vy_scale,
            "boost_descend_vy_bias": self._boost_descend_vy_bias,
            "boost_no_away_dir": self._boost_no_away_dir,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(
                f"PDG optimizer is not initialized: {', '.join(missing)}"
            )
        return required

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
        terminal_x_tol: float | None = None,
        y_ref_override: list[float] | tuple[float, ...] | Any | None = None,
        boost_t_cross_ref: float = 0.0,
        boost_t_angle_ref: float = 0.0,
        boost_no_away_dir: float = 0.0,
        boost_angle_active: float = 0.0,
    ) -> PDGPlan | None:
        if self._problem is None:
            return None
        state = self._require_solver_state()
        problem = state["problem"]
        x_var = state["x"]
        y_var = state["y"]
        vx_var = state["vx"]
        vy_var = state["vy"]
        ax_var = state["ax"]
        ay_var = state["ay"]
        x0 = state["x0"]
        y0 = state["y0"]
        vx0 = state["vx0"]
        vy0 = state["vy0"]
        target_x_param = state["target_x"]
        target_y_param = state["target_y"]
        y_floor_param = state["y_floor"]
        target_vy_param = state["target_vy"]
        a_max_param = state["a_max"]
        a_min_param = state["a_min"]
        a_nom_param = state["a_nom"]
        tilt_tan_param = state["tilt_tan"]
        x_ref_param = state["x_ref"]
        y_ref_param = state["y_ref"]
        vy_floor_param = state["vy_floor"]
        g_param = state["g_param"]
        x_tol_param = state["x_tol"]
        boost_pdx_time_ref_param = state["boost_pdx_time_ref"]
        boost_proj_target_param = state["boost_proj_target"]
        boost_proj_x_scale_param = state["boost_proj_x_scale"]
        boost_proj_vx_scale_param = state["boost_proj_vx_scale"]
        boost_cross_y_scale_param = state["boost_cross_y_scale"]
        boost_cross_vy_scale_param = state["boost_cross_vy_scale"]
        boost_cross_target_param = state["boost_cross_target"]
        boost_cross_drop_weighted_param = state["boost_cross_drop_weighted"]
        boost_angle_vx_scale_param = state["boost_angle_vx_scale"]
        boost_angle_vy_scale_param = state["boost_angle_vy_scale"]
        boost_angle_vy_bias_param = state["boost_angle_vy_bias"]
        boost_descend_vy_scale_param = state["boost_descend_vy_scale"]
        boost_descend_vy_bias_param = state["boost_descend_vy_bias"]
        boost_no_away_dir_param = state["boost_no_away_dir"]

        n = int(self._cfg.horizon_steps)

        x0.value = float(x)
        y0.value = float(y)
        vx0.value = float(vx)
        vy0.value = float(vy)
        target_x_param.value = float(target_x)
        target_y_param.value = float(target_y)
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
        y_floor_param.value = y_floor_profile
        target_vy_param.value = float(target_vy)
        a_max_param.value = max(0.1, float(max_thrust_accel))
        a_min_param.value = max(0.0, float(min_thrust_accel))
        a_nom_param.value = min(
            max(0.1, float(max_thrust_accel)),
            max(0.1, float(nominal_thrust_accel)),
        )
        tilt_tan_param.value = max(1e-3, math.tan(max(0.02, float(max_tilt_rad))))
        vy_floor_param.value = float(descent_floor_vy)
        g_param.value = max(0.0, float(gravity_mag))
        x_tol = (
            float(pad_half_width) if terminal_x_tol is None else float(terminal_x_tol)
        )
        x_tol_param.value = max(0.0, x_tol)
        boost_t_cross_ref = max(0.0, float(boost_t_cross_ref))
        boost_t_angle_ref = max(0.0, float(boost_t_angle_ref))
        boost_pdx_time_ref = np.maximum(
            boost_t_cross_ref
            - (np.arange(n + 1, dtype=float) * float(self._cfg.step_dt)),
            0.0,
        )
        boost_angle_time_ref = np.maximum(
            boost_t_angle_ref
            - (np.arange(n + 1, dtype=float) * float(self._cfg.step_dt)),
            0.0,
        )
        active = boost_pdx_time_ref > 1e-6
        boost_pdx_weight = np.zeros(n + 1, dtype=float)
        if np.any(active):
            active_count = int(np.count_nonzero(active))
            boost_pdx_weight[active] = np.arange(1, active_count + 1, dtype=float)
            boost_pdx_weight = boost_pdx_weight / float(np.sum(boost_pdx_weight))
        boost_weight_sqrt = np.sqrt(boost_pdx_weight)
        boost_cross_drop = (
            0.5 * max(0.0, float(gravity_mag)) * np.square(boost_pdx_time_ref)
        )
        boost_angle_vy_mag = max(0.0, float(gravity_mag)) * boost_angle_time_ref
        angle_weight_sqrt = boost_weight_sqrt * math.sqrt(
            max(0.0, float(boost_angle_active))
        )
        boost_pdx_time_ref_param.value = boost_pdx_time_ref
        boost_proj_target_param.value = boost_weight_sqrt * float(target_x)
        boost_proj_x_scale_param.value = boost_weight_sqrt
        boost_proj_vx_scale_param.value = boost_weight_sqrt * boost_pdx_time_ref
        boost_cross_y_scale_param.value = boost_weight_sqrt
        boost_cross_vy_scale_param.value = boost_weight_sqrt * boost_pdx_time_ref
        boost_cross_target_param.value = boost_weight_sqrt * float(target_y)
        boost_cross_drop_weighted_param.value = boost_weight_sqrt * boost_cross_drop
        boost_angle_vx_scale_param.value = angle_weight_sqrt * float(
            self._cfg.boost_angle_slope_target
        )
        boost_angle_vy_scale_param.value = angle_weight_sqrt
        boost_angle_vy_bias_param.value = angle_weight_sqrt * boost_angle_vy_mag
        boost_descend_vy_scale_param.value = boost_weight_sqrt
        boost_descend_vy_bias_param.value = boost_weight_sqrt * boost_angle_vy_mag
        boost_no_away_dir_param.value = float(boost_no_away_dir)

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
        x_ref_param.value = x_ref
        y_ref_param.value = y_ref

        if warm_start is not None and warm_start.feasible:
            shifted = warm_start.shifted()
            if len(shifted.ax) == n:
                ax_var.value = np.asarray(shifted.ax, dtype=float)
                ay_var.value = np.asarray(shifted.ay, dtype=float)
            if len(shifted.x) == n + 1:
                x_var.value = np.asarray(shifted.x, dtype=float)
                y_var.value = np.asarray(shifted.y, dtype=float)
                vx_var.value = np.asarray(shifted.vx, dtype=float)
                vy_var.value = np.asarray(shifted.vy, dtype=float)

        t0 = time.perf_counter()
        status = "error"
        try:
            problem.solve(
                solver=self._cfg.solver,
                warm_start=True,
                verbose=False,
                max_iter=self._cfg.solver_max_iters,
            )
            status = str(problem.status)
        except Exception:
            try:
                problem.solve(
                    solver="SCS",
                    warm_start=True,
                    verbose=False,
                    max_iters=250,
                )
                status = str(problem.status)
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

        ax_val = np.asarray(ax_var.value, dtype=float)
        ay_val = np.asarray(ay_var.value, dtype=float)
        x_val = np.asarray(x_var.value, dtype=float)
        y_val = np.asarray(y_var.value, dtype=float)
        vx_val = np.asarray(vx_var.value, dtype=float)
        vy_val = np.asarray(vy_var.value, dtype=float)

        objective = problem.value
        obj_val = (
            float(objective)
            if objective is not None and math.isfinite(float(objective))
            else 0.0
        )

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
