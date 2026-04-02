from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PDGConfig:
    # Receding horizon scheduling
    replan_hz_boost: float = 2.5
    replan_hz_terminal: float = 7.0
    replan_dx_error_boost: float = 48.0
    replan_dy_error_boost: float = 30.0
    replan_vx_error_boost: float = 7.0
    replan_vy_error_boost: float = 7.0
    replan_dx_error_terminal: float = 24.0
    replan_dy_error_terminal: float = 18.0
    replan_vx_error_terminal: float = 4.0
    replan_vy_error_terminal: float = 4.0
    fallback_hold_steps: int = 12
    long_horizon_altitude: float = 120.0
    long_horizon_time_to_go: float = 6.0
    force_terminal_from_start: bool = False

    # Attitude/allocator limits
    max_tilt: float = 0.78
    terminal_dynamic_tilt_max: float = 0.95
    boost_max_tilt: float = 1.05
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4
    uphill_boost_dy_min: float = 20.0
    uphill_boost_tilt_alt: float = 260.0
    uphill_boost_tilt_max: float = 0.30
    uphill_boost_relaxed_dy_max: float = 300.0
    uphill_boost_tilt_relaxed_max: float = 0.40
    downhill_boost_dy_min: float = 300.0
    downhill_boost_tilt_max: float = 1.18
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
    boost_cutoff_projected_dx_abs: float = 55.0
    boost_cutoff_projected_dx_target_ratio: float = 1.0
    boost_cutoff_idle_thrust_max: float = 0.03
    boost_cutoff_burn_start_thrust: float = 0.20
    boost_cutoff_burn_start_thrust_near: float = 0.10
    boost_cutoff_burn_start_thrust_far: float = 0.28
    boost_cutoff_burn_end_settle_s: float = 0.25
    boost_failure_cut_idle_s: float = 0.35
    boost_burn_max_s: float = 8.75
    boost_cutoff_apex_tol_abs: float = 18.0
    boost_cutoff_apex_tol_ratio: float = 0.20
    boost_active_thrust_floor: float = 0.70
    boost_active_thrust_floor_near: float = 0.45
    boost_active_thrust_floor_far: float = 0.72
    boost_late_thrust_weight: float = 0.50
    boost_distance_scale_near: float = 220.0
    boost_distance_scale_far: float = 700.0
    touchdown_phase_altitude: float = 4.0
    touchdown_phase_speed: float = 2.5
    touchdown_phase_dx_ratio: float = 0.65
    touchdown_phase_time_to_go: float = 3.5

    # Cheap analytic terminal gate: nominal-thrust readiness plus latest-safe fallback.
    terminal_gate_nominal_ratio: float = 0.92
    terminal_gate_nominal_min_up_accel: float = 0.5
    terminal_gate_nominal_buffer_s: float = 0.4
    terminal_gate_burn_time_min_s: float = 3.0
    terminal_gate_burn_time_max_s: float = 14.0
    terminal_gate_burn_time_offset_short_s: float = 0.8
    terminal_gate_burn_time_offset_long_s: float = 0.8
    terminal_gate_hysteresis_ticks: int = 2
    terminal_gate_latest_safe_buffer_s: float = 0.6
    terminal_overshoot_tilt_altitude_min: float = 35.0
    terminal_overshoot_tilt_projected_dx_abs: float = 28.0
    terminal_overshoot_tilt_projected_dx_ratio: float = 2.0
    terminal_overshoot_tilt_vx_min: float = 8.0
    terminal_overshoot_tilt_max: float = 1.22
    terrain_divert_enable: bool = True
    terrain_divert_body_margin: float = 2.0
    terrain_divert_trigger_margin: float = 10.0
    terrain_divert_min_boundary_steepness: float = 4.0
    terrain_divert_max_boundary_tail_steepness: float = 1.0
    terrain_divert_arm_overshoot: float = 18.0
    terrain_divert_arm_vx: float = 6.0
    terrain_divert_bias_per_meter: float = 0.080
    terrain_divert_bias_max: float = 16.0
    terrain_divert_release_overshoot: float = 120.0
    terrain_divert_release_vx: float = 14.0
    terrain_divert_containment_vx_gain: float = 0.22
    terrain_divert_containment_net_up: float = 0.35

    # Phase centering + boost/coast shape objective
    boost_center_tol_ratio: float = 0.20
    terminal_center_tol_ratio: float = 1.0
    boost_apex_height_per_dx: float = 0.18
    boost_apex_height_per_uphill_dy: float = 0.15
    boost_apex_height_min: float = 30.0
    boost_apex_height_max: float = 240.0
    boost_descent_angle_deg_min: float = 45.0
    boost_descent_angle_deg_target: float = 55.0
    boost_descent_angle_deg_max: float = 70.0

    # Launch-from-pad bootstrap when starting landed with a different target.
    launch_takeoff_clear_altitude: float = 10.0
    launch_takeoff_thrust: float = 0.9
