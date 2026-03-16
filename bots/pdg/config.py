from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PDGConfig:
    # Receding horizon scheduling
    replan_hz_setup: float = 2.5
    replan_hz_flare: float = 7.0
    replan_dx_error_setup: float = 48.0
    replan_dy_error_setup: float = 30.0
    replan_vx_error_setup: float = 7.0
    replan_vy_error_setup: float = 7.0
    replan_dx_error_flare: float = 24.0
    replan_dy_error_flare: float = 18.0
    replan_vx_error_flare: float = 4.0
    replan_vy_error_flare: float = 4.0
    fallback_hold_steps: int = 12
    long_horizon_altitude: float = 120.0
    long_horizon_time_to_go: float = 6.0
    force_flare_from_start: bool = False

    # Attitude/allocator limits
    max_tilt: float = 0.78
    flare_dynamic_tilt_max: float = 0.95
    setup_max_tilt: float = 1.05
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4
    uphill_setup_dy_min: float = 20.0
    uphill_setup_tilt_alt: float = 260.0
    uphill_setup_tilt_max: float = 0.30
    uphill_setup_relaxed_dy_max: float = 300.0
    uphill_setup_tilt_relaxed_max: float = 0.40
    downhill_setup_dy_min: float = 300.0
    downhill_setup_tilt_max: float = 1.18
    angle_rate: float = 2.4
    throttle_off_threshold_scale: float = 0.85

    # Braking-envelope vertical speed schedule (time-optimal leaning).
    braking_alt_margin: float = 6.0
    braking_tilt_scale: float = 1.00
    braking_accel_safety: float = 0.58
    braking_min_speed: float = 1.2
    braking_max_speed: float = 55.0
    braking_target_ratio: float = 0.48
    braking_floor_ratio: float = 0.22
    vy_low_alt_cap_alt: float = 40.0
    vy_low_alt_cap: float = 9.5
    vy_touch_cap_alt: float = 8.0
    vy_touch_cap: float = 2.4

    # Touchdown cut
    touchdown_zero_alt: float = 2.4
    touchdown_zero_vx: float = 0.55
    touchdown_zero_vy: float = 0.95
    touchdown_rescue_altitude: float = 4.5
    touchdown_rescue_vy_ratio: float = 1.8
    touchdown_rescue_tilt: float = 0.14
    touchdown_rescue_alt_floor: float = 0.8

    # Safety brake when descent rate is critical
    emergency_vy: float = 12.0
    emergency_alt: float = 220.0

    # Telemetry gates for focused launch/coast evals and phase tracking
    setup_gate_projected_dx_abs: float = 55.0
    setup_gate_projected_dx_target_ratio: float = 1.0
    setup_gate_idle_thrust_max: float = 0.03
    setup_gate_burn_start_thrust: float = 0.20
    setup_gate_burn_start_thrust_near: float = 0.10
    setup_gate_burn_start_thrust_far: float = 0.28
    setup_gate_burn_end_settle_s: float = 0.25
    setup_failure_cut_idle_s: float = 0.35
    setup_burn_max_s: float = 8.75
    setup_gate_apex_tol_abs: float = 18.0
    setup_gate_apex_tol_ratio: float = 0.20
    setup_active_thrust_floor: float = 0.70
    setup_active_thrust_floor_near: float = 0.45
    setup_active_thrust_floor_far: float = 0.72
    setup_late_thrust_weight: float = 0.50
    setup_distance_scale_near: float = 220.0
    setup_distance_scale_far: float = 700.0
    touchdown_phase_altitude: float = 4.0
    touchdown_phase_speed: float = 2.5
    touchdown_phase_dx_ratio: float = 0.65
    touchdown_phase_time_to_go: float = 3.5

    # Cheap analytic flare gate: nominal-thrust readiness plus latest-safe fallback.
    flare_gate_nominal_ratio: float = 0.92
    flare_gate_nominal_min_up_accel: float = 0.5
    flare_gate_nominal_buffer_s: float = 0.4
    flare_gate_burn_time_min_s: float = 3.0
    flare_gate_burn_time_max_s: float = 14.0
    flare_gate_burn_time_offset_short_s: float = 0.8
    flare_gate_burn_time_offset_long_s: float = 0.8
    flare_gate_hysteresis_ticks: int = 2
    flare_gate_latest_safe_buffer_s: float = 0.6
    flare_overshoot_tilt_altitude_min: float = 35.0
    flare_overshoot_tilt_projected_dx_abs: float = 28.0
    flare_overshoot_tilt_projected_dx_ratio: float = 2.0
    flare_overshoot_tilt_vx_min: float = 8.0
    flare_overshoot_tilt_max: float = 1.22

    # Phase centering + setup/coast shape objective
    setup_center_tol_ratio: float = 0.20
    flare_center_tol_ratio: float = 1.0
    setup_apex_height_per_dx: float = 0.18
    setup_apex_height_per_uphill_dy: float = 0.15
    setup_apex_height_min: float = 30.0
    setup_apex_height_max: float = 240.0
    setup_descent_angle_deg_min: float = 45.0
    setup_descent_angle_deg_target: float = 55.0
    setup_descent_angle_deg_max: float = 70.0

    # Launch-from-pad bootstrap when starting landed with a different target.
    launch_takeoff_clear_altitude: float = 10.0
    launch_takeoff_thrust: float = 0.9
