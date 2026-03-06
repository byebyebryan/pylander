from __future__ import annotations

from typing import Any

from core.eval_schema import BOT_ZEM_RESULT_FIELDS, EFFICIENCY_METRIC_FIELDS

_RUN_FIELDS: tuple[str, ...] = (
    "state",
    "eval_goal",
    "eval_early_end",
    "eval_end_reason",
    "time",
)

_OUTCOME_FIELDS: tuple[str, ...] = (
    "landing_count",
    "crash_count",
    "credits",
    "fuel",
    "score",
)

_FLIGHT_FIELDS: tuple[str, ...] = (
    "distance_flown",
    "landing_offset",
    "avg_speed",
    "fuel_consumed",
    "fuel_per_distance",
    "spawn_to_target_distance",
    "path_efficiency",
)

_SETUP_GOAL_FIELDS: tuple[str, ...] = (
    "setup_goal_done",
    "setup_goal_time",
    "setup_goal_fuel_consumed",
    "setup_goal_altitude",
    "setup_goal_projected_apex_y",
    "setup_goal_projected_apex_over_target",
    "setup_goal_has_target_y_solution",
    "setup_goal_projected_dx",
    "setup_goal_projected_impact_angle_deg",
    "setup_goal_burn_avg_thrust_level",
    "setup_goal_time_to_target",
)

_SETUP_GATE_FIELDS: tuple[str, ...] = (
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

_ARRIVAL_FIELDS: tuple[str, ...] = (
    "launch_arrived",
    "launch_landed_site_uid",
    "climb_arrived",
    "climb_landed_site_uid",
)

_PROFILER_FIELDS: tuple[str, ...] = (
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

_PLOT_FIELDS: tuple[str, ...] = (
    "plot_bundle_dir",
    "plot_manifest_path",
)

_FINAL_RESULT_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Run", _RUN_FIELDS),
    ("Outcome", _OUTCOME_FIELDS),
    ("Flight", _FLIGHT_FIELDS),
    ("Setup Goal", _SETUP_GOAL_FIELDS),
    ("Setup Gate", _SETUP_GATE_FIELDS),
    ("Arrivals", _ARRIVAL_FIELDS),
    ("Profiler", _PROFILER_FIELDS),
    ("Plots", _PLOT_FIELDS),
)


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _print_section(title: str, result: dict[str, Any], fields: tuple[str, ...]) -> int:
    rows = [(field, result[field]) for field in fields if field in result]
    if not rows:
        return 0
    print(f"\n[{title}]")
    width = max(len(field) for field, _value in rows)
    for field, value in rows:
        print(f"{field:<{width}} : {_format_value(value)}")
    return len(rows)


def _collect_bot_sections(result: dict[str, Any]) -> list[tuple[str, list[tuple[str, Any]]]]:
    grouped: dict[str, list[tuple[str, Any]]] = {}
    for key, value in result.items():
        if not isinstance(key, str) or not key.startswith("bot_"):
            continue
        if key.startswith("bot_profile_"):
            continue
        if key in BOT_ZEM_RESULT_FIELDS:
            bot_name = "zem_zev"
            label = key.removeprefix("bot_zem_zev_")
        else:
            parts = key.split("_", 2)
            if len(parts) < 3:
                continue
            bot_name = parts[1]
            label = parts[2]
        grouped.setdefault(bot_name, []).append((label, value))
    sections: list[tuple[str, list[tuple[str, Any]]]] = []
    for bot_name in sorted(grouped):
        rows = sorted(grouped[bot_name], key=lambda item: item[0])
        sections.append((bot_name, rows))
    return sections


def print_headless_results(result: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    printed = 0
    for title, fields in _FINAL_RESULT_SECTIONS:
        printed += _print_section(title, result, fields)
    for bot_name, rows in _collect_bot_sections(result):
        if not rows:
            continue
        print(f"\n[Bot Telemetry: {bot_name}]")
        width = max(len(field) for field, _value in rows)
        for field, value in rows:
            print(f"{field:<{width}} : {_format_value(value)}")
        printed += len(rows)
    if result.get("plot_paths"):
        print("\n[Plot Files]")
        for p in result["plot_paths"]:
            print(f"path : {p}")
    elif result.get("plot_path"):
        print("\n[Plot Files]")
        print(f"path : {result['plot_path']}")
    if result.get("plot_error"):
        print(f"plot_error : {result['plot_error']}")
    if printed == 0 and not result.get("plot_path") and not result.get("plot_paths"):
        print("(no result fields)")
    print("=" * 60)


def _print_efficiency_block(title: str, block: dict[str, Any] | None) -> None:
    if not block:
        return
    print(f"\n{title}:")
    printed = 0
    for metric in EFFICIENCY_METRIC_FIELDS:
        stats = block.get(metric)
        if not isinstance(stats, dict):
            continue
        count = int(stats.get("count", 0) or 0)
        if count <= 0:
            continue
        mean = float(stats.get("mean", 0.0) or 0.0)
        median = float(stats.get("median", 0.0) or 0.0)
        p90 = float(stats.get("p90", 0.0) or 0.0)
        print(
            f"  - {metric}: n={count} mean={mean:.2f} "
            f"median={median:.2f} p90={p90:.2f}"
        )
        printed += 1
    if printed == 0:
        print("  (no data)")


def print_batch_summary(
    summary: dict[str, Any],
    failures: list[dict[str, Any]],
    json_path,
    csv_path,
) -> None:
    print("\n" + "=" * 60)
    print("BATCH RESULTS")
    print("=" * 60)
    print(f"Runs:              {summary['runs']}")
    if "successes" in summary:
        print(f"Successes:         {summary['successes']}")
    print(f"Landed:            {summary['landed']}")
    print(f"Crashed:           {summary['crashed']}")
    print(f"Out_of_fuel:       {summary['out_of_fuel']}")
    print(f"Flying:            {summary['flying']}")
    print(f"Other:             {summary['other']}")
    print(f"Success rate:      {summary['success_rate']:.2%}")

    _print_efficiency_block("Efficiency (successful runs)", summary.get("efficiency_success"))
    _print_efficiency_block("Efficiency (all runs)", summary.get("efficiency_all"))

    if summary.get("by_scenario"):
        print("\nPer-scenario:")
        for name in sorted(summary["by_scenario"]):
            row = summary["by_scenario"][name]
            print(
                f"  - {name}: runs={row['runs']} landed={row['landed']} "
                f"crashed={row['crashed']} success={row['success_rate']:.2%}"
            )
            success_eff = row.get("efficiency_success") or {}
            fuel_stats = success_eff.get("fuel_consumed", {})
            time_stats = success_eff.get("time", {})
            fuel_mean = float(fuel_stats.get("mean", 0.0) or 0.0)
            time_mean = float(time_stats.get("mean", 0.0) or 0.0)
            fuel_count = int(fuel_stats.get("count", 0) or 0)
            if fuel_count > 0:
                print(
                    "      efficiency_success: "
                    f"fuel_mean={fuel_mean:.2f} time_mean={time_mean:.2f}"
                )

    if failures:
        print("\nFail samples:")
        for row in failures[:8]:
            print(
                f"  - seed={row.get('seed')} scenario={row.get('scenario') or 'default'} "
                f"state={row.get('state')}"
            )

    if json_path is not None:
        print(f"\nJSON report:       {json_path}")
    if csv_path is not None:
        print(f"CSV report:        {csv_path}")

    print("=" * 60)
