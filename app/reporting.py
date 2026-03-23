from __future__ import annotations

from typing import Any

from core.eval_schema import (
    BOT_PDG_RESULT_FIELDS,
    EFFICIENCY_METRIC_FIELDS,
    FINAL_RESULT_SECTIONS,
)
_FINAL_RESULTS_BAR_WIDTH = 60
_FINAL_RESULTS_VALUE_GAP = 4


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _label_width(
    section_rows: list[list[tuple[str, Any]]],
    bot_sections: list[tuple[str, list[tuple[str, Any]]]],
    trace_rows: list[tuple[str, Any]],
) -> int:
    labels: list[str] = []
    for rows in section_rows:
        labels.extend(field for field, _value in rows)
    for _bot_name, rows in bot_sections:
        labels.extend(field for field, _value in rows)
    labels.extend(field for field, _value in trace_rows)
    if not labels:
        return 0
    raw_width = max(len(label) for label in labels)
    return min(max(raw_width, 20), _FINAL_RESULTS_BAR_WIDTH - 8)


def _print_rows(rows: list[tuple[str, Any]], *, label_width: int) -> int:
    for field, value in rows:
        print(f"{field:<{label_width}}{' ' * _FINAL_RESULTS_VALUE_GAP}{_format_value(value)}")
    return len(rows)


def _print_section(
    title: str,
    rows: list[tuple[str, Any]],
    *,
    label_width: int,
) -> int:
    if not rows:
        return 0
    print(f"\n[{title}]")
    return _print_rows(rows, label_width=label_width)


def _collect_section_rows(
    result: dict[str, Any],
    fields: tuple[str, ...],
) -> list[tuple[str, Any]]:
    rows = [(field, result[field]) for field in fields if field in result]
    return rows


def _collect_bot_sections(result: dict[str, Any]) -> list[tuple[str, list[tuple[str, Any]]]]:
    grouped: dict[str, list[tuple[str, Any]]] = {}
    for key, value in result.items():
        if not isinstance(key, str) or not key.startswith("bot_"):
            continue
        if key.startswith("bot_profile_"):
            continue
        if key in BOT_PDG_RESULT_FIELDS:
            bot_name = "pdg"
            label = key.removeprefix("bot_pdg_")
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
    print("\n" + "=" * _FINAL_RESULTS_BAR_WIDTH)
    print("FINAL RESULTS")
    print("=" * _FINAL_RESULTS_BAR_WIDTH)
    section_rows = [
        _collect_section_rows(result, fields) for _title, fields in FINAL_RESULT_SECTIONS
    ]
    bot_sections = _collect_bot_sections(result)
    trace_rows: list[tuple[str, Any]] = []
    if result.get("trace_detail"):
        trace_rows.append(("trace_detail", result["trace_detail"]))
    if result.get("trace_path"):
        trace_rows.append(("trace_path", result["trace_path"]))
    if result.get("trace_rel_path"):
        trace_rows.append(("trace_rel_path", result["trace_rel_path"]))
    if result.get("trace_preview_path"):
        trace_rows.append(("preview_path", result["trace_preview_path"]))
    if result.get("trace_preview_rel_path"):
        trace_rows.append(("preview_rel_path", result["trace_preview_rel_path"]))
    label_width = _label_width(section_rows, bot_sections, trace_rows)
    printed = 0
    for (title, _fields), rows in zip(FINAL_RESULT_SECTIONS, section_rows, strict=False):
        printed += _print_section(title, rows, label_width=label_width)
    for bot_name, rows in bot_sections:
        if not rows:
            continue
        print(f"\n[Bot Telemetry: {bot_name}]")
        printed += _print_rows(rows, label_width=label_width)
    if trace_rows:
        print("\n[Trace Files]")
        _print_rows(trace_rows, label_width=label_width)
    if printed == 0 and not result.get("trace_path") and not result.get("trace_rel_path"):
        print("(no result fields)")
    print("=" * _FINAL_RESULTS_BAR_WIDTH)


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

    print("=" * 60)
