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
    "boost_goal_time",
    "boost_goal_fuel_consumed",
    "boost_goal_done",
    "boost_goal_altitude",
    "boost_goal_projected_apex_y",
    "boost_goal_projected_apex_over_target",
    "boost_goal_has_target_y_solution",
    "boost_goal_projected_dx",
    "boost_goal_projected_impact_angle_deg",
    "boost_goal_burn_avg_thrust_level",
    "boost_goal_time_to_target",
)

SETUP_GATE_RESULT_FIELDS: tuple[str, ...] = (
    "boost_cutoff_done",
    "boost_cutoff_time",
    "boost_cutoff_altitude",
    "boost_cutoff_projected_apex_y",
    "boost_cutoff_projected_apex_over_target",
    "boost_cutoff_has_target_y_solution",
    "boost_cutoff_projected_dx",
    "boost_cutoff_projected_impact_angle_deg",
    "boost_cutoff_burn_duration_s",
    "boost_cutoff_burn_fuel_used",
    "boost_cutoff_burn_avg_thrust_level",
)

ARRIVAL_RESULT_FIELDS: tuple[str, ...] = (
    "transfer_source_site_uid",
    "transfer_target_site_uid",
    "transfer_landed_site_uid",
    "transfer_arrived",
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
    "bot_pdg_terminal_entry_done",
    "bot_pdg_terminal_entry_time",
    "bot_pdg_terminal_entry_altitude",
    "bot_pdg_terminal_entry_projected_dx",
    "bot_pdg_terminal_post_entry_apex_gain",
    "bot_pdg_terminal_post_entry_time_to_apex",
    "bot_pdg_terminal_post_entry_peak_abs_dx",
    "bot_pdg_terminal_probe_count",
    "bot_pdg_terminal_probe_ms_mean",
    "bot_pdg_terminal_probe_ms_p90",
    "bot_pdg_terminal_gate_mode",
    "bot_pdg_terminal_gate_horizon_s",
    "bot_pdg_terminal_gate_terminal_speed",
    "bot_pdg_terminal_gate_peak_accel_ratio",
    "bot_pdg_terminal_gate_od_excess_s",
    "bot_pdg_terminal_gate_latest_safe_margin_s",
    "bot_pdg_terminal_gate_required_accel_ratio",
    "bot_pdg_solve_count",
    "bot_pdg_solve_ms_mean",
    "bot_pdg_solve_ms_p90",
    "bot_pdg_fallback_frames",
    "bot_pdg_boost_quality_verdict",
    "bot_pdg_boost_release_predicted_terminal_entry_projected_dx",
    "bot_pdg_boost_release_predicted_terminal_required_accel_ratio",
    "bot_pdg_boost_release_mode",
    "bot_pdg_shape_apex_error",
    "bot_pdg_shape_curve_rmse",
    "bot_pdg_shape_projected_dx_abs_mean",
    "bot_pdg_shape_projected_dx_abs_max",
    "bot_pdg_shape_shortfall_ratio",
)

TRACE_METRIC_RESULT_FIELDS: tuple[str, ...] = (
    "trace_ref_gap_mean",
    "trace_ref_gap_area",
    "trace_ref_gap_max",
)

TRACE_RESULT_FIELDS: tuple[str, ...] = (
    "trace_path",
    "trace_rel_path",
    "trace_preview_path",
    "trace_preview_rel_path",
    "trace_schema_version",
    "trace_sample_period_s",
    "trace_detail",
    "trace_snapshot_count",
    "trace_event_count",
    "trace_control_log_count",
    "run_key",
    "run_instance_id",
)

FINAL_RESULT_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Run", RUN_RESULT_FIELDS),
    ("Outcome", OUTCOME_RESULT_FIELDS),
    ("Flight", FLIGHT_RESULT_FIELDS),
    ("Boost Goal", SETUP_GOAL_RESULT_FIELDS),
    ("Boost Cutoff", SETUP_GATE_RESULT_FIELDS),
    ("Arrivals", ARRIVAL_RESULT_FIELDS),
    ("Profiler", BOT_PROFILE_RESULT_FIELDS),
    ("Trace Metrics", TRACE_METRIC_RESULT_FIELDS),
    ("Trace", TRACE_RESULT_FIELDS),
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
    *TRACE_METRIC_RESULT_FIELDS,
    *TRACE_RESULT_FIELDS,
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
    *tuple(field for field in SETUP_GOAL_RESULT_FIELDS if field != "boost_goal_done"),
    *tuple(field for field in SETUP_GATE_RESULT_FIELDS if field != "boost_cutoff_done"),
    *tuple(field for field in BOT_PROFILE_RESULT_FIELDS if field != "bot_profile_enabled"),
    "bot_pdg_terminal_entry_time",
    "bot_pdg_terminal_entry_altitude",
    "bot_pdg_terminal_entry_projected_dx",
    "bot_pdg_terminal_post_entry_apex_gain",
    "bot_pdg_terminal_post_entry_time_to_apex",
    "bot_pdg_terminal_post_entry_peak_abs_dx",
    "bot_pdg_solve_count",
    "bot_pdg_solve_ms_mean",
    "bot_pdg_solve_ms_p90",
    "bot_pdg_fallback_frames",
    "bot_pdg_boost_quality_verdict",
    "bot_pdg_boost_release_predicted_terminal_entry_projected_dx",
    "bot_pdg_boost_release_predicted_terminal_required_accel_ratio",
    "bot_pdg_shape_apex_error",
    "bot_pdg_shape_curve_rmse",
    "bot_pdg_shape_projected_dx_abs_mean",
    "bot_pdg_shape_projected_dx_abs_max",
    "bot_pdg_shape_shortfall_ratio",
    *TRACE_METRIC_RESULT_FIELDS,
)
