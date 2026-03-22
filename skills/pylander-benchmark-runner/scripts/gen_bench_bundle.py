from __future__ import annotations

import argparse
import html
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.selector_codec import render_record_selector  # noqa: E402
from skills.lib.orchestration import load_json, run_command  # noqa: E402

_SERVER_SCRIPT = (_REPO_ROOT / "skills" / "pylander-benchmark-runner" / "scripts" / "serve_outputs.py").resolve()
_SERVER_SERVICE_NAME = "pylander_outputs_server"
_SERVER_HEALTH_PATH = "/__pylander_viewer_health__"


def _sanitize_token(value: str) -> str:
    out = []
    prev_us = False
    for ch in str(value).lower().strip():
        if ch.isalnum() or ch in ("-", "."):
            out.append(ch)
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
                prev_us = True
    token = "".join(out).strip("._")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "run"


def _parse_section(output: str, section_name: str) -> dict[str, str]:
    marker = f"# {section_name.strip()}"
    lines = output.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() != marker:
            continue
        out: dict[str, str] = {}
        for next_line in lines[idx + 1 :]:
            stripped = next_line.strip()
            if not stripped:
                if out:
                    break
                continue
            if stripped.startswith("# "):
                break
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            out[key.strip()] = value.strip()
        return out
    return {}


def _output_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value.strip())
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _artifact_path(path_value: str | None, *, outputs_root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value).strip())
    if path.is_absolute():
        return path.resolve()
    if path.parts and path.parts[0] == "outputs":
        return (outputs_root.parent / path).resolve()
    return (outputs_root / path).resolve()


def _derive_meta_path(candidate_json: Path) -> Path:
    return candidate_json.with_name(f"{candidate_json.stem}.meta.json")


def _derive_csv_path(candidate_json: Path) -> Path:
    return candidate_json.with_suffix(".csv")


def _rel_to_outputs(path: Path | None, *, outputs_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(outputs_root).as_posix()
    except ValueError:
        return None


def _href_from(bundle_dir: Path, target_rel: str | None, *, outputs_root: Path) -> str | None:
    if not target_rel:
        return None
    target = outputs_root / target_rel
    rel = os.path.relpath(target, bundle_dir)
    return rel.replace(os.sep, "/")


def _format_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _format_seconds(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}s"
    except (TypeError, ValueError):
        return "-"


def _record_seed_sort_key(record: dict[str, Any]) -> tuple[int, int | str]:
    seed = record.get("seed")
    try:
        return (0, int(seed))
    except (TypeError, ValueError):
        token = str(seed).strip()
        return (1, token or "")


def _scenario_representative_sort_key(record: dict[str, Any]) -> tuple[int, int, tuple[int, int | str]]:
    success_rank = 1 if bool(record.get("success", False)) else 0
    crash_rank = 0 if str(record.get("state") or "").strip().lower() == "crashed" else 1
    return (success_rank, crash_rank, _record_seed_sort_key(record))


def _scenario_plot_selectors(candidate_payload: dict[str, Any]) -> list[str]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw_record in candidate_payload.get("records") or []:
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        scenario_selector = render_record_selector(record, include_seed=False)
        if not scenario_selector:
            continue
        current = grouped.get(scenario_selector)
        if current is None or _scenario_representative_sort_key(record) < _scenario_representative_sort_key(current):
            grouped[scenario_selector] = record

    selectors: list[str] = []
    for scenario_selector in sorted(grouped):
        selectors.append(render_record_selector(grouped[scenario_selector]))
    return selectors


def _all_run_plot_selectors(candidate_payload: dict[str, Any]) -> list[str]:
    records = [dict(item) for item in candidate_payload.get("records") or [] if isinstance(item, dict)]
    records.sort(key=lambda record: (_selector_sort_key(_scenario_selector_for_record(record)), _record_seed_sort_key(record)))
    selectors: list[str] = []
    for record in records:
        selector = render_record_selector(record)
        if selector:
            selectors.append(selector)
    return selectors


def _summary_metric(summary: dict[str, Any], field: str) -> dict[str, Any]:
    block = dict(summary.get("efficiency_success") or {})
    return dict(block.get(field) or {})


def _selector_rows(payload: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selector, row in dict(payload.get("summary", {}).get("by_selector") or {}).items():
        eff_success = dict(row.get("efficiency_success") or {})

        def _mean(metric: str) -> float:
            return float(dict(eff_success.get(metric) or {}).get("mean", 0.0) or 0.0)

        rows.append(
            {
                "selector": str(selector),
                "runs": int(row.get("runs", 0) or 0),
                "successes": int(row.get("successes", 0) or 0),
                "crashed": int(row.get("crashed", 0) or 0),
                "success_rate": float(row.get("success_rate", 0.0) or 0.0),
                "fuel_mean": _mean("fuel_consumed"),
                "time_mean": _mean("time"),
                "total_ms_mean": _mean("bot_profile_total_ms_per_tick"),
            }
        )
    rows.sort(
        key=lambda item: (
            float(item["success_rate"]),
            -int(item["crashed"]),
            -float(item["fuel_mean"]),
            -float(item["time_mean"]),
        )
    )
    return rows[: max(1, int(limit))]


def _failure_rows(payload: dict[str, Any], *, limit: int = 16) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in payload.get("records") or []:
        if not isinstance(record, dict) or bool(record.get("success", False)):
            continue
        rows.append(
            {
                "selector": (
                    f"{record.get('level') or 'unknown'}:"
                    f"{record.get('scenario') or 'default'}:"
                    f"{record.get('seed') if record.get('seed') is not None else '0'}"
                ),
                "state": str(record.get("state") or ""),
                "failure_mode": str(record.get("failure_mode") or ""),
                "fuel": record.get("fuel_consumed"),
                "time": record.get("time"),
            }
        )
    rows.sort(key=lambda item: item["selector"])
    return rows[: max(1, int(limit))]


def _compare_summary(compare_payload: dict[str, Any]) -> dict[str, Any]:
    global_block = dict(compare_payload.get("global") or {})
    crash_block = dict(global_block.get("crash") or {})
    return {
        "notable_regression": bool(compare_payload.get("notable_regression", False)),
        "new_global_crashes": list(crash_block.get("new_crashes") or []),
        "worst_scenarios": list(global_block.get("worst_scenarios") or []),
        "compute": dict(global_block.get("compute") or {}),
    }


def _root_path(path_rel: str | None) -> str | None:
    if not path_rel:
        return None
    return "/" + path_rel.lstrip("/")


def _summary_cards(summary: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Runs", str(int(summary.get("runs", 0) or 0))),
        ("Successes", str(int(summary.get("successes", 0) or 0))),
        ("Success Rate", _format_percent(summary.get("success_rate"))),
        ("Crashed", str(int(summary.get("crashed", 0) or 0))),
        ("Fuel Mean", _format_float(_summary_metric(summary, "fuel_consumed").get("mean"))),
        ("Time Mean", _format_float(_summary_metric(summary, "time").get("mean"))),
        (
            "Bot ms/tick",
            _format_float(_summary_metric(summary, "bot_profile_total_ms_per_tick").get("mean")),
        ),
        (
            "Bot p99",
            _format_float(_summary_metric(summary, "bot_profile_total_ms_per_tick_p99").get("mean")),
        ),
    ]


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    head_html = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        cols = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cols}</tr>")
    if not body_rows:
        body_rows.append(f"<tr><td colspan=\"{len(headers)}\">(none)</td></tr>")
    return (
        "<table>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_plot_cases(
    plot_pack: dict[str, Any] | None,
    *,
    bundle_dir: Path,
    outputs_root: Path,
) -> str:
    if not plot_pack:
        return "<p>No plots generated.</p>"

    cards: list[str] = []
    for case in plot_pack.get("cases") or []:
        if not isinstance(case, dict):
            continue
        selector = html.escape(str(case.get("selector") or "unknown"))
        reason = html.escape(str(case.get("reason") or ""))
        severity = html.escape(str(case.get("severity") or ""))
        command = " ".join(str(part) for part in (case.get("command") or []))
        preview_href = None
        plot_links: list[str] = []
        for raw_path in case.get("plot_paths") or []:
            target_rel = _rel_to_outputs(
                _artifact_path(str(raw_path), outputs_root=outputs_root),
                outputs_root=outputs_root,
            )
            href = _href_from(bundle_dir, target_rel, outputs_root=outputs_root)
            if href is None:
                continue
            label = html.escape(Path(str(raw_path)).name)
            if preview_href is None:
                preview_href = href
            plot_links.append(f"<a href=\"{html.escape(href)}\">{label}</a>")
        meta_links: list[str] = []
        for label, raw_path in (
            ("manifest", case.get("plot_manifest_path")),
            ("bundle_dir", case.get("plot_bundle_dir")),
        ):
            target_rel = _rel_to_outputs(
                _artifact_path(str(raw_path), outputs_root=outputs_root) if raw_path else None,
                outputs_root=outputs_root,
            )
            href = _href_from(bundle_dir, target_rel, outputs_root=outputs_root)
            if href is None:
                continue
            meta_links.append(f"<a href=\"{html.escape(href)}\">{html.escape(label)}</a>")

        preview_html = (
            f"<a href=\"{html.escape(preview_href)}\"><img src=\"{html.escape(preview_href)}\" alt=\"{selector}\"></a>"
            if preview_href
            else ""
        )
        cards.append(
            "<article class=\"plot-card\">"
            f"<h3>{selector}</h3>"
            f"<p class=\"meta\">severity={severity} reason={reason}</p>"
            f"{preview_html}"
            f"<p class=\"cmd\"><code>{html.escape(command)}</code></p>"
            f"<p class=\"links\">{' | '.join(plot_links + meta_links) if (plot_links or meta_links) else '(no plot links)'}</p>"
            "</article>"
        )
    return "<div class=\"plot-grid\">" + "".join(cards) + "</div>" if cards else "<p>No plots generated.</p>"


def _selector_sort_key(selector: str) -> tuple[tuple[int, int | str], ...]:
    parts = [part for part in str(selector).split(":") if part]
    key: list[tuple[int, int | str]] = []
    for part in parts:
        try:
            key.append((0, int(part)))
        except ValueError:
            key.append((1, part))
    return tuple(key)


def _scenario_selector_for_record(record: dict[str, Any]) -> str:
    return render_record_selector(record, include_seed=False)


def _record_detail_rel_path(bundle_id: str, record: dict[str, Any]) -> str:
    selector = render_record_selector(record)
    return f"viewer/bundles/{bundle_id}/runs/{_sanitize_token(selector)}.html"


def _load_plot_case_assets(case: dict[str, Any], *, outputs_root: Path) -> dict[str, Any] | None:
    manifest_path = _artifact_path(str(case.get("plot_manifest_path") or ""), outputs_root=outputs_root)
    manifest_payload: dict[str, Any] = {}
    if manifest_path is not None and manifest_path.exists():
        loaded = load_json(manifest_path)
        if isinstance(loaded, dict):
            manifest_payload = loaded

    plot_entries: list[dict[str, str]] = []
    manifest_plots = manifest_payload.get("plots") or []
    if isinstance(manifest_plots, list) and manifest_plots:
        for item in manifest_plots:
            if not isinstance(item, dict):
                continue
            path_rel = _rel_to_outputs(
                _artifact_path(str(item.get("path") or ""), outputs_root=outputs_root),
                outputs_root=outputs_root,
            )
            if not path_rel:
                continue
            plot_entries.append(
                {
                    "filename": str(item.get("filename") or Path(path_rel).name),
                    "path_rel": path_rel,
                }
            )
    else:
        for raw_path in case.get("plot_paths") or []:
            path_rel = _rel_to_outputs(
                _artifact_path(str(raw_path), outputs_root=outputs_root),
                outputs_root=outputs_root,
            )
            if not path_rel:
                continue
            plot_entries.append(
                {
                    "filename": Path(str(raw_path)).name,
                    "path_rel": path_rel,
                }
            )

    split_entries = [item for item in plot_entries if "/overview/" not in str(item.get("path_rel") or "")]
    preview_entry = next(
        (item for item in split_entries if str(item.get("filename") or "") == "spatial_trajectory_comparison.png"),
        None,
    )
    if preview_entry is None and split_entries:
        preview_entry = split_entries[0]

    return {
        "selector": str(case.get("selector") or ""),
        "command": list(case.get("command") or []),
        "plot_entries": plot_entries,
        "split_plot_entries": split_entries,
        "preview_entry": preview_entry,
        "manifest_path_rel": _rel_to_outputs(manifest_path, outputs_root=outputs_root),
        "bundle_dir_rel": _rel_to_outputs(
            _artifact_path(str(case.get("plot_bundle_dir") or ""), outputs_root=outputs_root),
            outputs_root=outputs_root,
        ),
        "events": list(manifest_payload.get("events") or []),
        "target": dict(manifest_payload.get("target") or {}),
    }


def _run_metric_cards(record: dict[str, Any]) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = [
        ("State", str(record.get("state") or "-")),
        ("Failure", str(record.get("failure_mode") or "-")),
        ("Fuel", _format_float(record.get("fuel_consumed"), 3)),
        ("Time", _format_float(record.get("time"), 3)),
    ]
    if record.get("landing_offset") is not None:
        cards.append(("Offset", _format_float(record.get("landing_offset"), 3)))
    if record.get("avg_speed") is not None:
        cards.append(("Avg Speed", _format_float(record.get("avg_speed"), 3)))
    if record.get("bot_profile_total_ms_per_tick") is not None:
        cards.append(("Bot ms/tick", _format_float(record.get("bot_profile_total_ms_per_tick"), 3)))
    return cards


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _scenario_summary_data(summary_row: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    eff_success = dict(summary_row.get("efficiency_success") or {})
    fuel_mean = dict(eff_success.get("fuel_consumed") or {}).get("mean")
    time_mean = dict(eff_success.get("time") or {}).get("mean")
    total_ms_mean = dict(eff_success.get("bot_profile_total_ms_per_tick") or {}).get("mean")
    if fuel_mean is None:
        fuel_mean = _mean([float(run["record"].get("fuel_consumed")) for run in runs if run["record"].get("fuel_consumed") is not None and bool(run["record"].get("success", False))])
    if time_mean is None:
        time_mean = _mean([float(run["record"].get("time")) for run in runs if run["record"].get("time") is not None and bool(run["record"].get("success", False))])
    if total_ms_mean is None:
        total_ms_mean = _mean(
            [
                float(run["record"].get("bot_profile_total_ms_per_tick"))
                for run in runs
                if run["record"].get("bot_profile_total_ms_per_tick") is not None and bool(run["record"].get("success", False))
            ]
        )

    return {
        "runs": int(summary_row.get("runs", len(runs)) or len(runs)),
        "successes": int(summary_row.get("successes", sum(1 for run in runs if bool(run["record"].get("success", False)))) or 0),
        "crashed": int(
            summary_row.get(
                "crashed",
                sum(1 for run in runs if str(run["record"].get("state") or "").strip().lower() == "crashed"),
            )
            or 0
        ),
        "success_rate": float(
            summary_row.get(
                "success_rate",
                (sum(1 for run in runs if bool(run["record"].get("success", False))) / float(len(runs))) if runs else 0.0,
            )
            or 0.0
        ),
        "fuel_mean": fuel_mean,
        "time_mean": time_mean,
        "total_ms_mean": total_ms_mean,
    }


def _build_bundle_report_model(bundle: dict[str, Any], *, outputs_root: Path) -> dict[str, Any]:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    summary = dict(candidate.get("summary") or {})
    plot_pack = dict(bundle.get("plot_pack") or {}) or None
    timing = dict(bundle.get("timing") or {})
    bundle_id = str(bundle.get("bundle_id") or "bundle")

    plot_assets_by_selector: dict[str, dict[str, Any]] = {}
    if plot_pack:
        for case in plot_pack.get("cases") or []:
            if not isinstance(case, dict):
                continue
            selector = str(case.get("selector") or "").strip()
            if not selector:
                continue
            assets = _load_plot_case_assets(case, outputs_root=outputs_root)
            if assets is not None:
                plot_assets_by_selector[selector] = assets

    records = [dict(item) for item in benchmark.get("records") or [] if isinstance(item, dict)]
    records.sort(key=lambda record: (_selector_sort_key(_scenario_selector_for_record(record)), _record_seed_sort_key(record)))

    runs_by_scenario: dict[str, list[dict[str, Any]]] = {}
    runs_by_selector: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    for record in records:
        run_selector = render_record_selector(record)
        scenario_selector = _scenario_selector_for_record(record)
        detail_rel = _record_detail_rel_path(bundle_id, record)
        plot_assets = plot_assets_by_selector.get(run_selector)
        run_info = {
            "selector": run_selector,
            "scenario_selector": scenario_selector,
            "record": record,
            "detail_rel": detail_rel,
            "plot": plot_assets,
        }
        runs_by_scenario.setdefault(scenario_selector, []).append(run_info)
        runs_by_selector[run_selector] = run_info
        if not bool(record.get("success", False)):
            failures.append(run_info)

    scenario_items: list[dict[str, Any]] = []
    for scenario_selector in sorted(runs_by_scenario, key=_selector_sort_key):
        runs = list(runs_by_scenario[scenario_selector])
        summary_row = dict(summary.get("by_selector", {}).get(scenario_selector) or {})
        representative_run = next((run for run in runs if run.get("plot") is not None), None)
        scenario_items.append(
            {
                "selector": scenario_selector,
                "level": scenario_selector.split(":", 1)[0],
                "tokens": scenario_selector.split(":"),
                "summary": _scenario_summary_data(summary_row, runs),
                "runs": runs,
                "representative_run": representative_run,
            }
        )

    scenarios_by_level: dict[str, list[dict[str, Any]]] = {}
    for item in scenario_items:
        scenarios_by_level.setdefault(str(item["level"]), []).append(item)

    failure_scenarios = sorted({item["scenario_selector"] for item in failures}, key=_selector_sort_key)
    quick_summary = [
        f"{int(summary.get('successes', 0) or 0)}/{int(summary.get('runs', 0) or 0)} successful across {len(scenario_items)} scenarios.",
        f"{len(plot_assets_by_selector)} run detail page(s) include split-image plot galleries.",
    ]
    if failure_scenarios:
        quick_summary.append(
            f"{int(summary.get('crashed', 0) or 0)} crash(es), all in {', '.join(failure_scenarios[:3])}{' ...' if len(failure_scenarios) > 3 else ''}."
        )
    timing_parts = []
    for label, key in (
        ("bench", "benchmark_wall_clock_s"),
        ("plots", "plot_pack_wall_clock_s"),
        ("render", "bundle_render_wall_clock_s"),
        ("total", "total_wall_clock_s"),
    ):
        if timing.get(key) is not None:
            timing_parts.append(f"{label}={_format_seconds(timing.get(key))}")
    if timing_parts:
        quick_summary.append("Wall clock: " + ", ".join(timing_parts) + ".")
    if timing.get("plot_workers") is not None:
        quick_summary.append(f"Plot workers: {int(timing.get('plot_workers') or 0)}.")

    return {
        "scenario_items": scenario_items,
        "scenarios_by_level": scenarios_by_level,
        "failures": sorted(failures, key=lambda item: _selector_sort_key(str(item.get("selector") or ""))),
        "runs_by_selector": runs_by_selector,
        "quick_summary": quick_summary,
    }


def _render_metric_card_grid(cards: list[tuple[str, str]]) -> str:
    return "".join(
        "<div class=\"card\">"
        f"<div class=\"label\">{html.escape(label)}</div>"
        f"<div class=\"value\">{html.escape(value)}</div>"
        "</div>"
        for label, value in cards
    )


def _render_events_table(events: list[dict[str, Any]]) -> str:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        rows.append(
            [
                html.escape(str(event.get("name") or "")),
                html.escape(str(event.get("label") or "")),
                _format_float(event.get("time_s"), 3),
                _format_float(event.get("x"), 3),
                _format_float(event.get("y"), 3),
            ]
        )
    return _render_table(["Name", "Label", "Time", "X", "Y"], rows)


def _render_scenario_sections(
    report: dict[str, Any],
    *,
    bundle_dir: Path,
    outputs_root: Path,
) -> str:
    sections: list[str] = []
    for level_name in sorted(report["scenarios_by_level"], key=_selector_sort_key):
        row_blocks: list[str] = []
        for item in report["scenarios_by_level"][level_name]:
            summary_data = dict(item.get("summary") or {})
            group_id = _sanitize_token(str(item["selector"]))
            aggregate_status = (
                f"{int(summary_data.get('successes', 0) or 0)}/{int(summary_data.get('runs', 0) or 0)} success"
                f" | crashed={int(summary_data.get('crashed', 0) or 0)}"
            )
            preview_cell = "<span class=\"muted\">expand</span>"
            representative_run = item.get("representative_run")
            if representative_run is not None and representative_run.get("plot") is not None:
                preview_entry = dict(representative_run["plot"].get("preview_entry") or {})
                preview_href = _href_from(bundle_dir, str(preview_entry.get("path_rel") or ""), outputs_root=outputs_root)
                detail_href = _href_from(bundle_dir, str(representative_run.get("detail_rel") or ""), outputs_root=outputs_root)
                if preview_href and detail_href:
                    preview_cell = (
                        f"<a class=\"table-preview\" href=\"{html.escape(detail_href)}\">"
                        f"<img src=\"{html.escape(preview_href)}\" alt=\"{html.escape(str(item['selector']))}\">"
                        "</a>"
                    )

            row_blocks.append(
                "<tr class=\"scenario-row\""
                f" data-group=\"{html.escape(group_id)}\" aria-expanded=\"false\" tabindex=\"0\">"
                f"<td><span class=\"expander\">+</span>{html.escape(str(item['selector']))}</td>"
                f"<td>{html.escape(aggregate_status)}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('fuel_mean')))}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('time_mean')))}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('total_ms_mean')))}</td>"
                f"<td>{preview_cell}</td>"
                f"<td>{len(item.get('runs') or [])}</td>"
                "</tr>"
            )

            for run in item.get("runs") or []:
                record = dict(run.get("record") or {})
                detail_href = _href_from(bundle_dir, str(run.get("detail_rel") or ""), outputs_root=outputs_root) or "#"
                preview_cell = "<span class=\"muted\">no plot</span>"
                plot_assets = dict(run.get("plot") or {})
                preview_entry = dict(plot_assets.get("preview_entry") or {})
                preview_href = _href_from(bundle_dir, str(preview_entry.get("path_rel") or ""), outputs_root=outputs_root)
                if preview_href:
                    preview_cell = (
                        f"<a class=\"table-preview\" href=\"{html.escape(detail_href)}\">"
                        f"<img src=\"{html.escape(preview_href)}\" alt=\"{html.escape(str(run.get('selector') or 'run'))}\">"
                        "</a>"
                    )
                metric_text = f"offset={_format_float(record.get('landing_offset'), 3)}"
                row_blocks.append(
                    "<tr class=\"seed-row\" hidden"
                    f" data-parent=\"{html.escape(group_id)}\">"
                    f"<td class=\"seed-label\">seed {html.escape(str(record.get('seed') if record.get('seed') is not None else '-'))}</td>"
                    f"<td>{html.escape(str(record.get('state') or ''))} / {html.escape(str(record.get('failure_mode') or ''))}</td>"
                    f"<td>{html.escape(_format_float(record.get('fuel_consumed'), 3))}</td>"
                    f"<td>{html.escape(_format_float(record.get('time'), 3))}</td>"
                    f"<td>{html.escape(metric_text)}</td>"
                    f"<td>{preview_cell}</td>"
                    f"<td><a href=\"{html.escape(detail_href)}\">detail</a></td>"
                    "</tr>"
                )
        sections.append(
            "<section>"
            f"<h2>{html.escape(level_name.title())}</h2>"
            "<div class=\"table-wrap\">"
            "<table class=\"scenario-table\">"
            "<thead><tr><th>Selector</th><th>Status</th><th>Fuel</th><th>Time</th><th>Metric</th><th>Trajectory</th><th>Link</th></tr></thead>"
            f"<tbody>{''.join(row_blocks)}</tbody>"
            "</table>"
            "</div>"
            + "</section>"
        )
    return "".join(sections)


def _render_failure_table(
    report: dict[str, Any],
    *,
    bundle_dir: Path,
    outputs_root: Path,
) -> str:
    rows = []
    for run in report.get("failures") or []:
        record = dict(run.get("record") or {})
        detail_href = _href_from(bundle_dir, str(run.get("detail_rel") or ""), outputs_root=outputs_root) or "#"
        rows.append(
            [
                f"<a href=\"{html.escape(detail_href)}\">{html.escape(str(run.get('selector') or ''))}</a>",
                html.escape(str(record.get("state") or "")),
                html.escape(str(record.get("failure_mode") or "")),
                _format_float(record.get("fuel_consumed"), 3),
                _format_float(record.get("time"), 3),
            ]
        )
    return _render_table(["Selector", "State", "Failure", "Fuel", "Time"], rows)


def _render_run_detail_html(
    bundle: dict[str, Any],
    run: dict[str, Any],
    *,
    bundle_dir: Path,
    outputs_root: Path,
    report: dict[str, Any],
) -> str:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    record = dict(run.get("record") or {})
    selector = str(run.get("selector") or "unknown")
    plot_assets = dict(run.get("plot") or {})
    detail_dir = (outputs_root / str(run["detail_rel"])).parent
    index_href = _href_from(detail_dir, str(bundle.get("bundle_page_path") or ""), outputs_root=outputs_root) or "../index.html"
    latest_href = _href_from(detail_dir, str(bundle.get("latest_page_path") or ""), outputs_root=outputs_root)
    candidate_href = _href_from(detail_dir, candidate.get("json_path"), outputs_root=outputs_root)
    manifest_href = _href_from(detail_dir, str(plot_assets.get("manifest_path_rel") or ""), outputs_root=outputs_root)
    bundle_dir_href = _href_from(detail_dir, str(plot_assets.get("bundle_dir_rel") or ""), outputs_root=outputs_root)

    cards = _render_metric_card_grid(_run_metric_cards(record))

    gallery = "<p class=\"muted\">No split plot images were generated for this specific run.</p>"
    if plot_assets.get("split_plot_entries"):
        gallery_cards: list[str] = []
        for entry in plot_assets.get("split_plot_entries") or []:
            if not isinstance(entry, dict):
                continue
            href = _href_from(detail_dir, str(entry.get("path_rel") or ""), outputs_root=outputs_root)
            if not href:
                continue
            gallery_cards.append(
                "<article class=\"plot-card\">"
                f"<h3>{html.escape(str(entry.get('filename') or 'plot'))}</h3>"
                f"<a href=\"{html.escape(href)}\"><img src=\"{html.escape(href)}\" alt=\"{html.escape(str(entry.get('filename') or 'plot'))}\"></a>"
                "</article>"
            )
        if gallery_cards:
            gallery = "<div class=\"plot-strip\">" + "".join(gallery_cards) + "</div>"

    scenario_selector = str(run.get("scenario_selector") or "")
    scenario_runs = list(report.get("runs_by_selector", {}).values())
    representative = next(
        (
            item
            for item in scenario_runs
            if str(item.get("scenario_selector") or "") == scenario_selector and item.get("plot") is not None
        ),
        None,
    )
    representative_href = None
    if representative is not None and representative is not run:
        representative_href = _href_from(detail_dir, str(representative.get("detail_rel") or ""), outputs_root=outputs_root)

    repro_cmd = html.escape(
        "uv run python main.py plot "
        f"{selector} --bot {html.escape(str(record.get('bot') or 'pdg'))} --plot all --plot-output split"
    )
    plot_cmd = html.escape(" ".join(str(item) for item in plot_assets.get("command") or []))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(selector)} • Pylander Run Detail</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1e8;
      --panel: #fffaf0;
      --ink: #1d1f24;
      --muted: #575f66;
      --accent: #0e6b60;
      --warn: #8e3b2e;
      --line: #d8cfbf;
      --shadow: rgba(29, 31, 36, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: linear-gradient(180deg, #f7f4ec 0%, var(--bg) 100%); }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px 48px; }}
    header, section, .card, .plot-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 24px var(--shadow); }}
    header, section {{ padding: 18px 20px; margin-bottom: 18px; }}
    h1, h2, h3 {{ margin: 0 0 10px; font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif; }}
    .meta, .links, .muted {{ color: var(--muted); }}
    .banner {{ display: inline-block; padding: 8px 12px; border-radius: 999px; font-weight: 700; background: rgba(14, 107, 96, 0.12); color: var(--accent); }}
    .banner.bad {{ background: rgba(142, 59, 46, 0.12); color: var(--warn); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 16px; }}
    .card {{ padding: 14px; }}
    .label {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .value {{ font-size: 1.35rem; margin-top: 6px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .plot-strip {{ display: grid; grid-auto-flow: column; grid-auto-columns: 280px; gap: 14px; overflow-x: auto; padding-bottom: 8px; }}
    .plot-card {{ padding: 14px; }}
    .plot-card img {{ width: 100%; height: 220px; display: block; object-fit: fill; border-radius: 12px; border: 1px solid var(--line); margin-top: 10px; background: #efe7da; }}
    code {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: 0.9rem; white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <main>
    <header>
      <p class="links"><a href="{html.escape(index_href)}">bundle report</a>{f' | <a href="{html.escape(latest_href)}">latest alias</a>' if latest_href else ''}</p>
      <h1>{html.escape(selector)}</h1>
      <p class="meta">scenario={html.escape(scenario_selector)}</p>
      <p class="banner {'bad' if not bool(record.get('success', False)) else ''}">{html.escape(str(record.get('state') or '-'))} / failure={html.escape(str(record.get('failure_mode') or '-'))}</p>
      <div class="cards">{cards}</div>
    </header>

    <section>
      <h2>Plots</h2>
      {gallery}
      <p class="links">{' | '.join(link for link in [
        f'<a href="{html.escape(candidate_href)}">candidate json</a>' if candidate_href else '',
        f'<a href="{html.escape(manifest_href)}">plot manifest</a>' if manifest_href else '',
        f'<a href="{html.escape(bundle_dir_href)}">plot bundle dir</a>' if bundle_dir_href else '',
        f'<a href="{html.escape(representative_href)}">scenario representative detail</a>' if representative_href else '',
      ] if link)}</p>
    </section>

    <section>
      <h2>Events</h2>
      {_render_events_table(list(plot_assets.get("events") or []))}
    </section>

    <section>
      <h2>Commands</h2>
      <details>
        <summary>Show repro commands</summary>
        <p><code>{repro_cmd}</code></p>
        <p><code>{plot_cmd}</code></p>
      </details>
    </section>
  </main>
</body>
</html>
"""


def _render_bundle_html(bundle: dict[str, Any], *, bundle_dir: Path, outputs_root: Path) -> str:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    compare = dict(bundle.get("compare") or {})
    summary = dict(candidate.get("summary") or {})
    report = _build_bundle_report_model(bundle, outputs_root=outputs_root)
    summary_cards = _render_metric_card_grid(_summary_cards(summary))

    raw_links: list[str] = []
    for label, path_rel in (
        ("candidate json", candidate.get("json_path")),
        ("candidate csv", candidate.get("csv_path")),
        ("candidate meta", candidate.get("meta_path")),
        ("compare report", compare.get("json_path")),
        ("plot pack", dict(bundle.get("plot_pack") or {}).get("manifest_path")),
        ("bundle json", bundle.get("bundle_json_path")),
    ):
        href = _href_from(bundle_dir, path_rel, outputs_root=outputs_root)
        if href is None:
            continue
        raw_links.append(f"<a href=\"{html.escape(href)}\">{html.escape(label)}</a>")

    compare_html = ""
    if compare:
        worst_rows = _render_table(
            ["Scenario", "Delta Success", "Delta Fuel", "Basis"],
            [
                [
                    html.escape(str(row.get("scenario") or "")),
                    _format_float(row.get("delta_success_rate"), 3),
                    _format_float(row.get("delta_fuel_mean"), 3),
                    html.escape(str(row.get("fuel_basis") or "")),
                ]
                for row in compare.get("worst_scenarios") or []
            ],
        )
        crash_rows = _render_table(
            ["Level", "Scenario", "Seed", "Failure", "Baseline State"],
            [
                [
                    html.escape(str(item.get("level") or "")),
                    html.escape(str(item.get("scenario") or "")),
                    html.escape(str(item.get("seed") or "")),
                    html.escape(str(item.get("candidate_failure_mode") or "")),
                    html.escape(str(item.get("baseline_state") or "")),
                ]
                for item in compare.get("new_global_crashes") or []
            ],
        )
        compare_html = (
            "<section>"
            "<h2>Compare</h2>"
            f"<p class=\"banner {'bad' if compare.get('notable_regression') else 'ok'}\">"
            f"notable_regression={html.escape(str(compare.get('notable_regression')))}</p>"
            "<h3>New Global Crashes</h3>"
            f"{crash_rows}"
            "<h3>Worst Scenarios</h3>"
            f"{worst_rows}"
            "</section>"
        )

    benchmark_cmd = html.escape(" ".join(str(item) for item in benchmark.get("command") or []))
    plot_cmd = html.escape(" ".join(str(item) for item in dict(bundle.get("plot_pack") or {}).get("command") or []))
    latest_href = _href_from(bundle_dir, bundle.get("latest_page_path"), outputs_root=outputs_root)
    quick_summary_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in report.get("quick_summary") or [])
    scenario_sections_html = _render_scenario_sections(report, bundle_dir=bundle_dir, outputs_root=outputs_root)
    failure_table = _render_failure_table(report, bundle_dir=bundle_dir, outputs_root=outputs_root)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(str(bundle.get('title') or 'Pylander Bench Bundle'))}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1e8;
      --panel: #fffaf0;
      --ink: #1d1f24;
      --muted: #575f66;
      --accent: #0e6b60;
      --warn: #8e3b2e;
      --line: #d8cfbf;
      --shadow: rgba(29, 31, 36, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(14, 107, 96, 0.10), transparent 28%),
        linear-gradient(180deg, #f7f4ec 0%, var(--bg) 100%);
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px 20px 48px;
    }}
    h1, h2, h3 {{
      margin: 0 0 10px;
      font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif;
    }}
    p, li {{ line-height: 1.45; }}
    header {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 30px var(--shadow);
      padding: 20px 22px;
      margin-bottom: 20px;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .banner {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      font-weight: 700;
      margin: 6px 0 0;
    }}
    .banner.ok {{ background: rgba(14, 107, 96, 0.12); color: var(--accent); }}
    .banner.bad {{ background: rgba(142, 59, 46, 0.12); color: var(--warn); }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin: 18px 0 10px;
    }}
    .card, section, .plot-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 24px var(--shadow);
    }}
    .card {{
      padding: 14px;
    }}
    .label {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .value {{
      font-size: 1.5rem;
      margin-top: 6px;
    }}
    section {{
      padding: 18px 20px;
      margin-top: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      font-size: 0.9rem;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}
    .links {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .summary-list {{
      margin: 0;
      padding-left: 20px;
    }}
    .table-wrap {{ overflow-x: auto; }}
    .scenario-table {{
      width: 100%;
      min-width: 860px;
    }}
    .scenario-row {{
      cursor: pointer;
      background: rgba(14, 107, 96, 0.04);
    }}
    .scenario-row:hover {{
      background: rgba(14, 107, 96, 0.08);
    }}
    .scenario-row td:first-child {{
      font-weight: 700;
    }}
    .scenario-row .expander {{
      display: inline-block;
      width: 1.25rem;
      color: var(--accent);
      font-weight: 700;
    }}
    .scenario-row[aria-expanded="true"] .expander {{
      transform: rotate(45deg);
    }}
    .seed-row {{
      background: rgba(255, 250, 240, 0.55);
    }}
    .seed-label {{
      padding-left: 28px;
      color: var(--muted);
    }}
    .table-preview {{
      display: inline-block;
      width: 120px;
    }}
    .table-preview img {{
      width: 120px;
      height: 72px;
      display: block;
      object-fit: fill;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #efe7da;
    }}
    .muted {{
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      main {{ padding: 18px 14px 36px; }}
      section {{ padding: 16px; }}
      th, td {{ padding: 7px 8px; }}
      .table-preview {{
        width: 96px;
      }}
      .table-preview img {{
        width: 96px;
        height: 64px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(str(bundle.get("title") or "Pylander Bench Bundle"))}</h1>
      <p class="meta">created_at_utc={html.escape(str(bundle.get("created_at_utc") or ""))}</p>
      <p class="meta">bundle_id={html.escape(str(bundle.get("bundle_id") or ""))}</p>
      <p class="banner {'bad' if int(summary.get('crashed', 0) or 0) > 0 else 'ok'}">
        benchmark_exit_code={html.escape(str(benchmark.get("exit_code")))} cached={html.escape(str(candidate.get("cached")))}
      </p>
      <div class="cards">{summary_cards}</div>
      <p class="links">{' | '.join(raw_links)}</p>
      <p class="links">{f'<a href="{html.escape(latest_href)}">latest alias</a>' if latest_href else ''}</p>
      <details>
        <summary>Show commands</summary>
        <p><code>{benchmark_cmd}</code></p>
        <p><code>{plot_cmd}</code></p>
      </details>
    </header>

    <section>
      <h2>Quick Summary</h2>
      <ul class="summary-list">{quick_summary_html}</ul>
    </section>

    {compare_html}

    {scenario_sections_html}

    <section>
      <h2>Failures</h2>
      {failure_table}
    </section>
  </main>
  <script>
    const toggleScenarioRows = (row) => {{
      const group = row.dataset.group;
      if (!group) return;
      const expanded = row.getAttribute("aria-expanded") === "true";
      row.setAttribute("aria-expanded", expanded ? "false" : "true");
      document.querySelectorAll(`tr[data-parent="${{group}}"]`).forEach((child) => {{
        child.hidden = expanded;
      }});
    }};

    document.querySelectorAll(".scenario-row").forEach((row) => {{
      row.addEventListener("click", (event) => {{
        if (event.target.closest("a")) return;
        toggleScenarioRows(row);
      }});
      row.addEventListener("keydown", (event) => {{
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        toggleScenarioRows(row);
      }});
    }});
  </script>
</body>
</html>
"""


def _redirect_html(target_href: str) -> str:
    escaped = html.escape(target_href)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={escaped}">
  <title>Latest Pylander Bundle</title>
</head>
<body>
  <p>Redirecting to <a href="{escaped}">{escaped}</a>.</p>
</body>
</html>
"""


def _benchmark_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
        "--mode",
        args.mode,
        "--bot",
        args.bot,
        "--results-dir",
        args.results_dir,
        "--crash-detail-limit",
        str(max(0, int(args.crash_detail_limit))),
    ]
    if args.seed_spec:
        cmd.extend(["--seed-spec", args.seed_spec])
    if args.selectors:
        cmd.extend(["--selectors", *args.selectors])
    if args.exclude_levels:
        cmd.extend(["--exclude-levels", *args.exclude_levels])
    if args.observe_only_levels:
        cmd.extend(["--observe-only-levels", *args.observe_only_levels])
    if args.bot_config:
        cmd.extend(["--bot-config", args.bot_config])
    if args.bot_profile:
        cmd.append("--bot-profile")
    else:
        cmd.append("--no-bot-profile")
    if args.bot_profile_interval_s is not None:
        cmd.extend(["--bot-profile-interval-s", str(args.bot_profile_interval_s)])
    if args.bot_profile_logs:
        cmd.append("--bot-profile-logs")
    else:
        cmd.append("--no-bot-profile-logs")
    if args.baseline_ref:
        cmd.extend(["--baseline-ref", args.baseline_ref])
    if args.no_reuse:
        cmd.append("--no-reuse")
    return cmd


def _plot_pack_command(
    *,
    benchmark_json: Path,
    candidate_payload: dict[str, Any],
    compare_json: Path | None,
    bundle_plot_manifest: Path,
    args: argparse.Namespace,
) -> list[str]:
    mode = "triage" if compare_json is not None else "health"
    cmd = [
        "uv",
        "run",
        "python",
        "skills/pylander-plot-runner/scripts/build_plot_pack.py",
        "--mode",
        mode,
        "--benchmark-json",
        str(benchmark_json),
        "--bot",
        args.bot,
        "--top-n",
        str(max(1, int(args.top_plots))),
        "--plot-mode",
        args.plot_mode,
        "--plot-output",
        args.plot_output,
        "--plot-max-side-px",
        str(max(256, int(args.plot_max_side_px))),
        "--plot-workers",
        str(int(args.plot_workers)),
        "--output-manifest",
        str(bundle_plot_manifest),
    ]
    plot_scope = str(args.plot_scope).strip().lower()
    selectors: list[str] | None = None
    if plot_scope == "per-scenario":
        selectors = _scenario_plot_selectors(candidate_payload)
    elif plot_scope == "per-run":
        selectors = _all_run_plot_selectors(candidate_payload)
    if selectors is not None:
        if not selectors:
            raise SystemExit(f"Unable to resolve {plot_scope} plot selectors from benchmark records.")
        cmd[cmd.index("--mode") + 1] = "focus"
        cmd[cmd.index("--top-n") + 1] = str(len(selectors))
        cmd.extend(["--selectors", *selectors])
    if compare_json is not None:
        cmd.extend(["--compare-json", str(compare_json)])
    return cmd


def _bundle_payload(
    *,
    bundle_id: str,
    created_at_utc: str,
    benchmark_cmd: list[str],
    benchmark_exit_code: int,
    benchmark_wall_clock_s: float,
    candidate_json_path: Path,
    candidate_csv_path: Path,
    candidate_meta_path: Path,
    candidate_payload: dict[str, Any],
    candidate_cached: str | None,
    compare_path: Path | None,
    compare_payload: dict[str, Any] | None,
    plot_pack_cmd: list[str] | None,
    plot_pack_exit_code: int | None,
    plot_pack_wall_clock_s: float | None,
    plot_pack_path: Path | None,
    plot_pack_payload: dict[str, Any] | None,
    plot_scope: str,
    outputs_root: Path,
) -> dict[str, Any]:
    latest_page = "viewer/latest/index.html"
    bundle_page = f"viewer/bundles/{bundle_id}/index.html"
    bundle_json = f"viewer/bundles/{bundle_id}/bundle.json"
    return {
        "bundle_id": bundle_id,
        "created_at_utc": created_at_utc,
        "title": f"Pylander Bench Bundle {bundle_id}",
        "latest_page_path": latest_page,
        "bundle_page_path": bundle_page,
        "bundle_json_path": bundle_json,
        "timing": {
            "benchmark_wall_clock_s": float(benchmark_wall_clock_s),
            "plot_pack_wall_clock_s": None if plot_pack_wall_clock_s is None else float(plot_pack_wall_clock_s),
            "bundle_render_wall_clock_s": None,
            "total_wall_clock_s": None,
            "plot_workers": (
                int(dict(plot_pack_payload or {}).get("plot_workers"))
                if dict(plot_pack_payload or {}).get("plot_workers") is not None
                else None
            ),
        },
        "benchmark": {
            "command": benchmark_cmd,
            "exit_code": int(benchmark_exit_code),
            "records": [dict(item) for item in candidate_payload.get("records") or [] if isinstance(item, dict)],
            "candidate": {
                "cached": candidate_cached,
                "json_path": _rel_to_outputs(candidate_json_path, outputs_root=outputs_root),
                "csv_path": _rel_to_outputs(candidate_csv_path, outputs_root=outputs_root),
                "meta_path": _rel_to_outputs(candidate_meta_path, outputs_root=outputs_root),
                "summary": dict(candidate_payload.get("summary") or {}),
            },
            "failures": _failure_rows(candidate_payload),
        },
        "compare": (
            {
                "json_path": _rel_to_outputs(compare_path, outputs_root=outputs_root),
                **_compare_summary(compare_payload or {}),
            }
            if compare_path and compare_payload is not None
            else None
        ),
        "plot_pack": (
            {
                "command": plot_pack_cmd,
                "exit_code": plot_pack_exit_code,
                "selection_scope": plot_scope,
                "manifest_path": _rel_to_outputs(plot_pack_path, outputs_root=outputs_root),
                "cases": list(plot_pack_payload.get("cases") or []),
            }
            if plot_pack_path is not None and plot_pack_payload is not None
            else None
        ),
    }


def _write_bundle_files(
    bundle: dict[str, Any],
    *,
    outputs_root: Path,
) -> tuple[Path, Path, Path]:
    render_started = time.perf_counter()
    bundle_page_rel = Path(str(bundle["bundle_page_path"]))
    bundle_dir = (outputs_root / bundle_page_rel).parent
    bundle_dir.mkdir(parents=True, exist_ok=True)
    report = _build_bundle_report_model(bundle, outputs_root=outputs_root)
    detail_payloads: list[tuple[Path, str]] = []

    for run in report.get("runs_by_selector", {}).values():
        if not isinstance(run, dict):
            continue
        detail_rel = str(run.get("detail_rel") or "").strip()
        if not detail_rel:
            continue
        detail_path = outputs_root / detail_rel
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_payloads.append(
            (
                detail_path,
                _render_run_detail_html(
                    bundle,
                    run,
                    bundle_dir=bundle_dir,
                    outputs_root=outputs_root,
                    report=report,
                ),
            )
        )

    render_elapsed = time.perf_counter() - render_started
    timing = dict(bundle.get("timing") or {})
    timing["bundle_render_wall_clock_s"] = render_elapsed
    timing["total_wall_clock_s"] = sum(
        float(timing.get(key) or 0.0)
        for key in ("benchmark_wall_clock_s", "plot_pack_wall_clock_s", "bundle_render_wall_clock_s")
    )
    bundle["timing"] = timing

    bundle_json_path = outputs_root / str(bundle["bundle_json_path"])
    bundle_json_path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")

    html_path = outputs_root / str(bundle["bundle_page_path"])
    html_path.write_text(
        _render_bundle_html(bundle, bundle_dir=bundle_dir, outputs_root=outputs_root),
        encoding="utf-8",
    )

    for detail_path, detail_html in detail_payloads:
        detail_path.write_text(
            detail_html,
            encoding="utf-8",
        )

    latest_path = outputs_root / str(bundle["latest_page_path"])
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_href = _href_from(latest_path.parent, str(bundle["bundle_page_path"]), outputs_root=outputs_root)
    latest_path.write_text(_redirect_html(latest_href or "../bundles/"), encoding="utf-8")
    return html_path, bundle_json_path, latest_path


def _normalize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    base = str(value).strip().rstrip("/")
    if not base:
        return None
    return base


def _bundle_url(base_url: str | None, rel_path: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url}/{rel_path.lstrip('/')}"


def _local_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        return host or None
    except OSError:
        return None
    finally:
        sock.close()


def _resolves_to_nonloopback(hostname: str) -> bool:
    try:
        addr = socket.gethostbyname(hostname)
    except OSError:
        return False
    return not addr.startswith("127.")


def _discover_viewer_hostname() -> str:
    short_host = str(socket.gethostname() or "").strip()
    short_label = short_host.split(".", 1)[0]
    fqdn = str(socket.getfqdn() or "").strip()

    candidates: list[str] = []
    if short_label:
        candidates.append(f"{short_label}.lan")
    if fqdn and "." in fqdn and fqdn not in candidates:
        candidates.append(fqdn)
    if short_host and "." in short_host and short_host not in candidates:
        candidates.append(short_host)

    for candidate in candidates:
        if _resolves_to_nonloopback(candidate):
            return candidate

    ip_addr = _local_ip()
    if ip_addr:
        return ip_addr
    return short_label or "localhost"


def _server_health(port: int) -> dict[str, Any] | None:
    health_url = f"http://127.0.0.1:{int(port)}{_SERVER_HEALTH_PATH}"
    try:
        with urllib.request.urlopen(health_url, timeout=0.75) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("service") or "") != _SERVER_SERVICE_NAME:
        return None
    return payload


def _write_server_state(
    *,
    outputs_root: Path,
    status: str,
    port: int,
    bind_host: str,
    viewer_hostname: str,
    pid: int | None,
) -> Path:
    state_path = (outputs_root / "viewer" / "server.json").resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "service": _SERVER_SERVICE_NAME,
        "status": status,
        "bind_host": bind_host,
        "port": int(port),
        "viewer_hostname": viewer_hostname,
        "viewer_base_url": f"http://{viewer_hostname}:{int(port)}",
        "pid": pid,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return state_path


def _ensure_outputs_server(
    *,
    outputs_root: Path,
    bind_host: str,
    port: int,
    viewer_hostname: str,
) -> tuple[str, Path]:
    existing = _server_health(port)
    state_path = _write_server_state(
        outputs_root=outputs_root,
        status=("running" if existing else "starting"),
        port=port,
        bind_host=bind_host,
        viewer_hostname=viewer_hostname,
        pid=None,
    )
    if existing is not None:
        return "reused", state_path

    log_path = (outputs_root / "viewer" / "server.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(_SERVER_SCRIPT),
                "--host",
                bind_host,
                "--port",
                str(int(port)),
                "--root",
                str(outputs_root),
            ],
            cwd=str(_REPO_ROOT),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _write_server_state(
        outputs_root=outputs_root,
        status="starting",
        port=port,
        bind_host=bind_host,
        viewer_hostname=viewer_hostname,
        pid=proc.pid,
    )

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _server_health(port) is not None:
            _write_server_state(
                outputs_root=outputs_root,
                status="running",
                port=port,
                bind_host=bind_host,
                viewer_hostname=viewer_hostname,
                pid=proc.pid,
            )
            return "started", state_path
        time.sleep(0.1)

    raise SystemExit(
        "Outputs server failed to become healthy on "
        f"http://127.0.0.1:{int(port)}{_SERVER_HEALTH_PATH}. "
        f"Check {log_path} for details."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Run cached benchmark and write a static HTML bundle")
    ap.add_argument("--mode", choices=("smoke", "quick", "full", "focused"), required=True)
    ap.add_argument("--seed-spec", default=None)
    ap.add_argument("--selectors", nargs="*", default=[])
    ap.add_argument("--exclude-levels", nargs="*", default=[])
    ap.add_argument("--observe-only-levels", nargs="*", default=[])
    ap.add_argument("--bot", default="pdg")
    ap.add_argument("--bot-config", default=None)
    ap.add_argument("--bot-profile", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--bot-profile-interval-s", type=float, default=None)
    ap.add_argument("--bot-profile-logs", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--baseline-ref", default=None)
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument("--no-reuse", action="store_true")
    ap.add_argument("--crash-detail-limit", type=int, default=8)
    ap.add_argument("--top-plots", type=int, default=8)
    ap.add_argument("--plot-scope", choices=("top", "per-scenario", "per-run"), default="top")
    ap.add_argument("--plot-mode", choices=("speed", "thrust", "all"), default="all")
    ap.add_argument("--plot-output", choices=("combined", "split", "both"), default="both")
    ap.add_argument("--plot-max-side-px", type=int, default=1800)
    ap.add_argument("--plot-workers", type=int, default=0)
    ap.add_argument("--viewer-base-url", default=None)
    ap.add_argument("--viewer-hostname", default=None)
    ap.add_argument("--server-port", type=int, default=8765)
    ap.add_argument("--server-bind-host", default="0.0.0.0")
    ap.add_argument("--ensure-server", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    outputs_root = (_REPO_ROOT / "outputs").resolve()
    created_at_utc = datetime.now(timezone.utc).isoformat()
    viewer_hostname = str(args.viewer_hostname or "").strip() or _discover_viewer_hostname()
    server_state_path: Path | None = None
    server_status = "disabled"
    if args.ensure_server:
        server_status, server_state_path = _ensure_outputs_server(
            outputs_root=outputs_root,
            bind_host=str(args.server_bind_host),
            port=int(args.server_port),
            viewer_hostname=viewer_hostname,
        )
    benchmark_cmd = _benchmark_command(args)
    benchmark_started = time.perf_counter()
    benchmark_exit_code, benchmark_output = run_command(benchmark_cmd, cwd=_REPO_ROOT)
    benchmark_wall_clock_s = time.perf_counter() - benchmark_started

    candidate_section = _parse_section(benchmark_output, "candidate")
    candidate_json_path = _output_path(candidate_section.get("json"))
    if candidate_json_path is None or not candidate_json_path.exists():
        raise SystemExit(
            "Unable to resolve candidate benchmark JSON from run_cached_benchmark output.\n"
            f"exit_code={benchmark_exit_code}\n{benchmark_output}"
        )
    candidate_csv_path = _output_path(candidate_section.get("csv")) or _derive_csv_path(candidate_json_path)
    candidate_meta_path = _output_path(candidate_section.get("meta")) or _derive_meta_path(candidate_json_path)

    candidate_payload = load_json(candidate_json_path)
    compare_section = _parse_section(benchmark_output, "compare_report")
    compare_path = _output_path(compare_section.get("json"))
    compare_payload = (
        load_json(compare_path)
        if compare_path is not None and compare_path.exists()
        else None
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_id = _sanitize_token(f"{ts}_{candidate_json_path.stem}")
    bundle_dir = (outputs_root / "viewer" / "bundles" / bundle_id).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    plot_pack_cmd: list[str] | None = None
    plot_pack_exit_code: int | None = None
    plot_pack_wall_clock_s: float | None = None
    plot_pack_path: Path | None = None
    plot_pack_payload: dict[str, Any] | None = None

    if str(args.plot_scope).strip().lower() in {"per-scenario", "per-run"} or int(args.top_plots) > 0:
        plot_pack_path = bundle_dir / "plot_pack.json"
        plot_pack_cmd = _plot_pack_command(
            benchmark_json=candidate_json_path,
            candidate_payload=candidate_payload,
            compare_json=compare_path if compare_payload is not None else None,
            bundle_plot_manifest=plot_pack_path,
            args=args,
        )
        plot_pack_started = time.perf_counter()
        plot_pack_exit_code, _plot_output = run_command(plot_pack_cmd, cwd=_REPO_ROOT)
        plot_pack_wall_clock_s = time.perf_counter() - plot_pack_started
        if plot_pack_path.exists():
            plot_pack_payload = load_json(plot_pack_path)

    bundle = _bundle_payload(
        bundle_id=bundle_id,
        created_at_utc=created_at_utc,
        benchmark_cmd=benchmark_cmd,
        benchmark_exit_code=benchmark_exit_code,
        benchmark_wall_clock_s=benchmark_wall_clock_s,
        candidate_json_path=candidate_json_path,
        candidate_csv_path=candidate_csv_path,
        candidate_meta_path=candidate_meta_path,
        candidate_payload=candidate_payload,
        candidate_cached=candidate_section.get("cached"),
        compare_path=compare_path,
        compare_payload=compare_payload,
        plot_pack_cmd=plot_pack_cmd,
        plot_pack_exit_code=plot_pack_exit_code,
        plot_pack_wall_clock_s=plot_pack_wall_clock_s,
        plot_pack_path=plot_pack_path if plot_pack_payload is not None else None,
        plot_pack_payload=plot_pack_payload,
        plot_scope=str(args.plot_scope),
        outputs_root=outputs_root,
    )
    bundle_page_path, bundle_json_path, latest_page_path = _write_bundle_files(
        bundle,
        outputs_root=outputs_root,
    )

    latest_rel = _rel_to_outputs(latest_page_path, outputs_root=outputs_root) or "viewer/latest/index.html"
    bundle_rel = _rel_to_outputs(bundle_page_path, outputs_root=outputs_root) or str(bundle["bundle_page_path"])
    bundle_json_rel = _rel_to_outputs(bundle_json_path, outputs_root=outputs_root) or str(bundle["bundle_json_path"])
    base_url = _normalize_base_url(args.viewer_base_url) or f"http://{viewer_hostname}:{int(args.server_port)}"
    latest_url = _bundle_url(base_url, latest_rel)
    bundle_url = _bundle_url(base_url, bundle_rel)

    print("# bench_bundle")
    print(f"server_status={server_status}")
    print(f"viewer_base_url={base_url}")
    print(f"plot_scope={args.plot_scope}")
    print(f"benchmark_wall_clock_s={benchmark_wall_clock_s:.3f}")
    if plot_pack_wall_clock_s is not None:
        print(f"plot_pack_wall_clock_s={plot_pack_wall_clock_s:.3f}")
    timing = dict(bundle.get("timing") or {})
    if timing.get("bundle_render_wall_clock_s") is not None:
        print(f"bundle_render_wall_clock_s={float(timing['bundle_render_wall_clock_s']):.3f}")
    if timing.get("total_wall_clock_s") is not None:
        print(f"total_wall_clock_s={float(timing['total_wall_clock_s']):.3f}")
    if timing.get("plot_workers") is not None:
        print(f"plot_workers={int(timing['plot_workers'])}")
    if server_state_path is not None:
        print(f"server_state={server_state_path}")
    print(f"candidate_json={candidate_json_path}")
    print(f"candidate_csv={candidate_csv_path}")
    print(f"candidate_meta={candidate_meta_path}")
    if compare_path is not None:
        print(f"compare_json={compare_path}")
    if plot_pack_path is not None and plot_pack_payload is not None:
        print(f"plot_pack_manifest={plot_pack_path}")
    print(f"bundle_page={bundle_page_path}")
    print(f"bundle_json={bundle_json_path}")
    print(f"latest_page={latest_page_path}")
    print(f"latest_rel={_root_path(latest_rel) or '/viewer/latest/index.html'}")
    print(f"bundle_rel={_root_path(bundle_rel) or '/viewer/bundles/'}")
    print(f"bundle_json_rel={_root_path(bundle_json_rel) or '/viewer/bundles/'}")
    if bundle_url:
        print(f"bundle_url={bundle_url}")
    if latest_url:
        print(f"latest_url={latest_url}")

    raise SystemExit(benchmark_exit_code)


if __name__ == "__main__":
    main()
