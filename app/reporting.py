from __future__ import annotations

from typing import Any

from core.eval_schema import EFFICIENCY_METRIC_FIELDS, HEADLESS_RESULT_FIELDS


def print_headless_results(result: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    for key in HEADLESS_RESULT_FIELDS:
        if key not in result:
            continue
        val = result[key]
        if isinstance(val, float):
            print(f"{key.capitalize():<24}{val:.2f}")
        else:
            print(f"{key.capitalize():<24}{val}")
    print("=" * 60)
    if result.get("plot_paths"):
        print("Plots:")
        for p in result["plot_paths"]:
            print(f"  {p}")
    elif result.get("plot_path"):
        print(f"Plot:              {result['plot_path']}")
    if result.get("plot_error"):
        print(f"Plot error:        {result['plot_error']}")
    if result.get("plot_manifest_path"):
        print(f"Plot manifest:     {result['plot_manifest_path']}")


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
