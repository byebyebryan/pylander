from __future__ import annotations

RUN_RESULT_FIELDS: tuple[str, ...] = (
    "state",
    "eval_goal",
    "eval_early_end",
    "eval_end_reason",
    "time",
)

OUTCOME_RESULT_FIELDS: tuple[str, ...] = (
    "landing_count",
    "crash_count",
    "credits",
    "fuel",
    "score",
)

FLIGHT_RESULT_FIELDS: tuple[str, ...] = (
    "distance_flown",
    "landing_offset",
    "avg_speed",
    "fuel_consumed",
    "fuel_per_distance",
    "spawn_to_target_distance",
    "path_efficiency",
)

SETUP_GOAL_RESULT_FIELDS: tuple[str, ...] = (
    "setup_goal_time",
    "setup_goal_fuel_consumed",
    "setup_goal_done",
    "setup_goal_altitude",
    "setup_goal_projected_apex_y",
    "setup_goal_projected_apex_over_target",
    "setup_goal_has_target_y_solution",
    "setup_goal_projected_dx",
    "setup_goal_projected_impact_angle_deg",
    "setup_goal_burn_avg_thrust_level",
    "setup_goal_time_to_target",
)

SETUP_GATE_RESULT_FIELDS: tuple[str, ...] = (
    "setup_gate_done",
    "setup_gate_time",
    "setup_gate_altitude",
    "setup_gate_projected_apex_y",
    "setup_gate_projected_apex_over_target",
    "setup_gate_has_target_y_solution",
    "setup_gate_projected_dx",
    "setup_gate_projected_impact_angle_deg",
    "setup_gate_burn_duration_s",
    "setup_gate_burn_fuel_used",
    "setup_gate_burn_avg_thrust_level",
)

ARRIVAL_RESULT_FIELDS: tuple[str, ...] = (
    "setup_transfer_source_site_uid",
    "setup_transfer_target_site_uid",
    "setup_transfer_landed_site_uid",
    "setup_transfer_arrived",
)

BOT_PROFILE_RESULT_FIELDS: tuple[str, ...] = (
    "bot_profile_enabled",
    "bot_profile_ticks",
    "bot_profile_passive_ms_per_tick",
    "bot_profile_update_ms_per_tick",
    "bot_profile_total_ms_per_tick",
    "bot_profile_update_ms_per_tick_p90",
    "bot_profile_update_ms_per_tick_p99",
    "bot_profile_total_ms_per_tick_p90",
    "bot_profile_total_ms_per_tick_p99",
)

BOT_PDG_RESULT_FIELDS: tuple[str, ...] = (
    "bot_pdg_flare_entry_done",
    "bot_pdg_flare_entry_time",
    "bot_pdg_flare_entry_altitude",
    "bot_pdg_flare_entry_projected_dx",
    "bot_pdg_flare_probe_count",
    "bot_pdg_flare_probe_ms_mean",
    "bot_pdg_flare_probe_ms_p90",
    "bot_pdg_flare_gate_mode",
    "bot_pdg_flare_gate_horizon_s",
    "bot_pdg_flare_gate_terminal_speed",
    "bot_pdg_flare_gate_peak_accel_ratio",
    "bot_pdg_flare_gate_od_excess_s",
    "bot_pdg_flare_gate_latest_safe_margin_s",
    "bot_pdg_flare_gate_required_accel_ratio",
    "bot_pdg_solve_count",
    "bot_pdg_solve_ms_mean",
    "bot_pdg_solve_ms_p90",
    "bot_pdg_fallback_frames",
    "bot_pdg_shape_apex_error",
    "bot_pdg_shape_curve_rmse",
    "bot_pdg_shape_projected_dx_abs_mean",
    "bot_pdg_shape_projected_dx_abs_max",
    "bot_pdg_shape_shortfall_ratio",
)

PLOT_RESULT_FIELDS: tuple[str, ...] = (
    "plot_bundle_dir",
    "plot_manifest_path",
)

FINAL_RESULT_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Run", RUN_RESULT_FIELDS),
    ("Outcome", OUTCOME_RESULT_FIELDS),
    ("Flight", FLIGHT_RESULT_FIELDS),
    ("Setup Goal", SETUP_GOAL_RESULT_FIELDS),
    ("Setup Gate", SETUP_GATE_RESULT_FIELDS),
    ("Arrivals", ARRIVAL_RESULT_FIELDS),
    ("Profiler", BOT_PROFILE_RESULT_FIELDS),
    ("Plots", PLOT_RESULT_FIELDS),
)

HEADLESS_RESULT_FIELDS: tuple[str, ...] = (
    *RUN_RESULT_FIELDS,
    *OUTCOME_RESULT_FIELDS,
    *FLIGHT_RESULT_FIELDS,
    *SETUP_GOAL_RESULT_FIELDS,
    *ARRIVAL_RESULT_FIELDS,
    *SETUP_GATE_RESULT_FIELDS,
    *BOT_PROFILE_RESULT_FIELDS,
    *BOT_PDG_RESULT_FIELDS,
    *PLOT_RESULT_FIELDS,
)

EFFICIENCY_METRIC_FIELDS: tuple[str, ...] = (
    "distance_flown",
    "landing_offset",
    "avg_speed",
    "fuel_consumed",
    "fuel_remaining",
    "fuel_per_distance",
    "overdrive_time",
    "overdrive_fraction",
    "overdrive_excess",
    "path_efficiency",
    "time",
    "time_to_first_land",
    *tuple(field for field in SETUP_GOAL_RESULT_FIELDS if field != "setup_goal_done"),
    *tuple(field for field in SETUP_GATE_RESULT_FIELDS if field != "setup_gate_done"),
    *tuple(field for field in BOT_PROFILE_RESULT_FIELDS if field != "bot_profile_enabled"),
    "bot_pdg_flare_entry_time",
    "bot_pdg_flare_entry_altitude",
    "bot_pdg_flare_entry_projected_dx",
    "bot_pdg_solve_count",
    "bot_pdg_solve_ms_mean",
    "bot_pdg_solve_ms_p90",
    "bot_pdg_fallback_frames",
    "bot_pdg_shape_apex_error",
    "bot_pdg_shape_curve_rmse",
    "bot_pdg_shape_projected_dx_abs_mean",
    "bot_pdg_shape_projected_dx_abs_max",
    "bot_pdg_shape_shortfall_ratio",
)
