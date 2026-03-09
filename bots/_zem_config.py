from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZemZevConfig:
    # Receding horizon scheduling
    replan_hz_setup: float = 2.5
    replan_hz_terminal: float = 7.0
    replan_dx_error_setup: float = 48.0
    replan_dy_error_setup: float = 30.0
    replan_vx_error_setup: float = 7.0
    replan_vy_error_setup: float = 7.0
    replan_dx_error_terminal: float = 24.0
    replan_dy_error_terminal: float = 18.0
    replan_vx_error_terminal: float = 4.0
    replan_vy_error_terminal: float = 4.0
    fallback_hold_steps: int = 12
    long_horizon_altitude: float = 120.0
    long_horizon_time_to_go: float = 6.0

    # Attitude/allocator limits
    max_tilt: float = 0.78
    max_tilt_low_alt: float = 0.18
    max_tilt_low_alt_far: float = 0.34
    low_alt_tilt_alt: float = 20.0
    low_alt_tilt_dx: float = 12.0
    low_alt_tilt_vx: float = 2.4
    uphill_setup_dy_min: float = 20.0
    uphill_setup_tilt_alt: float = 140.0
    uphill_setup_tilt_max: float = 0.26
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
    setup_gate_vx_track_abs: float = 3.8
    setup_gate_vx_track_ratio: float = 0.18
    setup_gate_vy_up_max: float = -1.0
    setup_gate_shortfall_abs: float = 20.0
    setup_gate_shortfall_ratio: float = 0.30
    setup_gate_idle_thrust_max: float = 0.03
    setup_gate_burn_start_thrust: float = 0.20
    setup_gate_burn_end_settle_s: float = 0.25
    setup_burn_taper_start_abs: float = 72.0
    setup_burn_taper_start_ratio: float = 1.30
    setup_burn_taper_overshoot_abs: float = 120.0
    setup_burn_taper_overshoot_ratio: float = 2.20
    setup_burn_cut_overshoot_abs: float = 4.0
    setup_burn_cut_overshoot_ratio: float = 0.08
    terminal_gate_t_fall_s: float = 4.5
    terminal_gate_projected_dx_abs: float = 18.0
    terminal_gate_projected_dx_target_ratio: float = 0.4
    terminal_gate_vy_up_max: float = -4.0
    terminal_entry_altitude_max: float = 260.0
    terminal_entry_vy_up_max: float = -12.0
    terminal_entry_projected_dx_abs: float = 70.0
    terminal_entry_projected_dx_target_ratio: float = 1.30
    touchdown_phase_altitude: float = 4.0
    touchdown_phase_speed: float = 2.5
    touchdown_phase_dx_ratio: float = 0.65

    # Phase centering + setup/coast shape objective
    setup_center_tol_ratio: float = 0.20
    terminal_center_tol_ratio: float = 1.0
    setup_apex_height_per_dx: float = 0.18
    setup_apex_height_min: float = 30.0
    setup_apex_height_max: float = 240.0
    setup_apex_ref_blend: float = 0.45

    # Launch-from-pad bootstrap when starting landed with a different target.
    launch_takeoff_clear_altitude: float = 10.0
    launch_takeoff_thrust: float = 0.9
