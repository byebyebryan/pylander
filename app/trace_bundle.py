from __future__ import annotations

import argparse
import html
import json
import math
import shlex
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.benchmark_analyze import build_analysis_payload
from app.benchmark_context import (
    analysis_sidecar_path,
    build_auto_intent,
    build_inspect_payload,
    discover_compare_path,
    inspect_sidecar_path,
    intent_sidecar_path,
    load_intent,
)
from app.benchmark_cache import load_json, tracepack_meta_path, write_json
from app.output_viewer import (
    bundle_url,
    discover_viewer_hostname,
    ensure_outputs_server,
    normalize_base_url,
)
from app.selector_pack import build_selectors

from game.core.selector_codec import render_record_selector
from bot_framework.scenarios import (
    resolve_scenario_binding as resolve_selector_binding,
    scenario_children,
    selector_path_looks_like_seed,
)
from game.levels.registry import list_public_levels
from tooling.tracebundle import (
    artifact_path as _artifact_path,
    href_from_outputs as _href_from,
    output_path as _output_path,
    rel_to_outputs as _rel_to_outputs,
    sanitize_token as _sanitize_token,
)
from tooling.traceviewer import (
    PLOTLY_CDN_URL,
    ensure_viewer_assets,
    render_trace_detail_html,
)

selector_children = scenario_children

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class BundleRenderResult:
    bundle: dict[str, Any]
    candidate_json_path: Path
    candidate_meta_path: Path
    compare_path: Path | None
    intent_path: Path | None
    analysis_path: Path | None
    bundle_page_path: Path
    bundle_json_path: Path
    latest_page_path: Path


def run_command(cmd: list[str], *, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = str(proc.stdout or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return int(proc.returncode), output


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


def _derive_meta_path(candidate_json: Path) -> Path:
    return tracepack_meta_path(candidate_json)


def _format_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100.0:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _record_seed_sort_key(record: dict[str, Any]) -> tuple[int, int | str]:
    seed = record.get("seed")
    if seed is None:
        return (1, "")
    try:
        return (0, int(seed))
    except (TypeError, ValueError):
        token = str(seed).strip()
        return (1, token or "")


def _scenario_representative_sort_key(
    record: dict[str, Any],
) -> tuple[int, int, tuple[int, int | str]]:
    success_rank = 1 if bool(record.get("success", False)) else 0
    crash_rank = 0 if str(record.get("state") or "").strip().lower() == "crashed" else 1
    return (success_rank, crash_rank, _record_seed_sort_key(record))


def _summary_metric(
    summary: dict[str, Any], field: str, *, scope: str = "success"
) -> dict[str, Any]:
    scope_key = (
        "efficiency_all"
        if str(scope).strip().lower() == "all"
        else "efficiency_success"
    )
    block = dict(summary.get(scope_key) or {})
    return dict(block.get(field) or {})


def _selector_rows(payload: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selector, row in dict(
        payload.get("summary", {}).get("by_selector") or {}
    ).items():
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
        "summary_available": bool(global_block.get("summary_available", True)),
        "summary_baseline": dict(global_block.get("summary_baseline") or {}),
        "summary_candidate": dict(global_block.get("summary_candidate") or {}),
        "summary_delta": dict(global_block.get("summary_delta") or {}),
        "compare_basis": dict(global_block.get("compare_basis") or {}),
    }


def _intent_summary(intent_payload: dict[str, Any]) -> dict[str, Any]:
    repo_context = dict(intent_payload.get("repo_context") or {})
    baseline_plan = dict(intent_payload.get("baseline_plan") or {})
    return {
        "goal_summary": str(intent_payload.get("goal_summary") or ""),
        "request_source": str(intent_payload.get("request_source") or ""),
        "conversation_context": [
            str(item).strip()
            for item in intent_payload.get("conversation_context") or []
            if str(item).strip()
        ],
        "changed_files": [
            str(item).strip()
            for item in repo_context.get("changed_files") or []
            if str(item).strip()
        ],
        "touched_areas": [
            str(item).strip()
            for item in repo_context.get("touched_areas") or []
            if str(item).strip()
        ],
        "baseline_strategy": str(baseline_plan.get("strategy") or ""),
        "baseline_requested_ref": str(baseline_plan.get("requested_ref") or ""),
        "baseline_missing_policy": str(
            baseline_plan.get("missing_baseline_policy") or ""
        ),
        "baseline_resolved_ref": str(baseline_plan.get("resolved_ref") or ""),
        "baseline_skipped_commits": [
            dict(item)
            for item in baseline_plan.get("skipped_commits") or []
            if isinstance(item, dict)
        ],
        "assumptions": [
            str(item).strip()
            for item in intent_payload.get("assumptions") or []
            if str(item).strip()
        ],
    }


def _analysis_summary(analysis_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": str(analysis_payload.get("verdict") or ""),
        "summary": str(analysis_payload.get("summary") or ""),
        "measured_evidence": [
            str(item).strip()
            for item in analysis_payload.get("measured_evidence") or []
            if str(item).strip()
        ],
        "likely_causes": [
            str(item).strip()
            for item in analysis_payload.get("likely_causes") or []
            if str(item).strip()
        ],
        "confidence": str(analysis_payload.get("confidence") or ""),
        "follow_ups": [
            str(item).strip()
            for item in analysis_payload.get("follow_ups") or []
            if str(item).strip()
        ],
    }


def _root_path(path_rel: str | None) -> str | None:
    if not path_rel:
        return None
    return "/" + path_rel.lstrip("/")


def _viewer_base_url(
    *,
    viewer_base_url: str | None,
    viewer_hostname: str,
    server_port: int,
    server_status: str,
) -> str | None:
    explicit = normalize_base_url(viewer_base_url)
    if explicit is not None:
        return explicit
    if server_status in {"started", "reused"}:
        return f"http://{viewer_hostname}:{int(server_port)}"
    return None


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    head_html = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        cols = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cols}</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(headers)}">(none)</td></tr>')
    return (
        "<table>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_table_with_row_classes(
    headers: list[str],
    rows: list[tuple[str, list[str]]],
    *,
    table_class: str = "",
) -> str:
    table_class_attr = f' class="{html.escape(table_class)}"' if table_class else ""
    head_html = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body_rows = []
    for row_class, row in rows:
        class_attr = f' class="{html.escape(row_class)}"' if row_class else ""
        cols = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr{class_attr}>{cols}</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(headers)}">(none)</td></tr>')
    return (
        f"<table{table_class_attr}>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _selector_sort_key(selector: str) -> tuple[tuple[int, int | str], ...]:
    parts = [part for part in str(selector).split(":") if part]
    key: list[tuple[int, int | str]] = []
    if not parts:
        return tuple()

    level = parts[0]
    level_order = {name: idx for idx, name in enumerate(list_public_levels())}
    if level in level_order:
        key.append((0, level_order[level]))
    else:
        key.append((1, level))

    prefix: tuple[str, ...] = ()
    for part in parts[1:]:
        if selector_path_looks_like_seed(part):
            try:
                key.append((2, int(part)))
            except ValueError:
                key.append((3, part))
            continue
        try:
            children = selector_children(level, prefix)
        except ValueError:
            children = ()
        if part in children:
            key.append((0, children.index(part)))
            prefix = (*prefix, part)
            continue
        key.append((3, part))
        prefix = (*prefix, part)
    return tuple(key)


def _scenario_selector_for_record(record: dict[str, Any]) -> str:
    return render_record_selector(record, include_seed=False)


def _record_detail_rel_path(
    bundle_id: str,
    record: dict[str, Any],
    *,
    source: str = "candidate",
) -> str:
    run_key = str(record.get("run_key") or "").strip()
    if not run_key:
        run_key = render_record_selector(record)
    source_prefix = (
        "runs" if source == "candidate" else f"runs/{_sanitize_token(source)}"
    )
    return f"viewer/bundles/{bundle_id}/{source_prefix}/{_sanitize_token(run_key)}.html"


def _baseline_candidate_json_path(
    bundle: dict[str, Any], *, outputs_root: Path
) -> Path | None:
    compare = dict(bundle.get("compare") or {})
    explicit_rel = str(compare.get("baseline_json_path") or "").strip()
    if explicit_rel:
        explicit_path = (outputs_root / explicit_rel).resolve()
        return explicit_path
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    baseline_commit = str(compare.get("baseline_commit") or "").strip()
    candidate_json_rel = str(candidate.get("json_path") or "").strip()
    if not baseline_commit or not candidate_json_rel:
        return None
    candidate_json_path = outputs_root / candidate_json_rel
    return (
        outputs_root / "benchmarks" / baseline_commit / candidate_json_path.name
    ).resolve()


def _compare_tracepack_path(path_value: Any, *, outputs_root: Path) -> Path | None:
    token = str(path_value or "").strip()
    if not token:
        return None
    path = Path(token).expanduser()
    if not path.is_absolute():
        path = (outputs_root / token).resolve()
    return path.resolve()


def _tracepack_ref_from_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.parent.name or None
    except (AttributeError, TypeError, ValueError):
        return None


def _load_trace_asset_paths(
    record: dict[str, Any], *, outputs_root: Path
) -> dict[str, Any]:
    trace_path = _artifact_path(
        str(record.get("trace_rel_path") or record.get("trace_path") or ""),
        outputs_root=outputs_root,
    )
    preview_path = _artifact_path(
        str(
            record.get("trace_preview_rel_path")
            or record.get("trace_preview_path")
            or ""
        ),
        outputs_root=outputs_root,
    )
    return {
        "trace_path": str(trace_path) if trace_path is not None else None,
        "trace_path_rel": _rel_to_outputs(trace_path, outputs_root=outputs_root),
        "preview_path": str(preview_path) if preview_path is not None else None,
        "preview_path_rel": _rel_to_outputs(preview_path, outputs_root=outputs_root),
    }


def _load_trace_payload(run: dict[str, Any], *, outputs_root: Path) -> dict[str, Any]:
    trace_path = _artifact_path(
        str(run.get("trace_path_rel") or run.get("trace_path") or ""),
        outputs_root=outputs_root,
    )
    if trace_path is None or not trace_path.exists():
        return {}
    loaded = load_json(trace_path)
    return dict(loaded) if isinstance(loaded, dict) else {}


def _load_plot_case_assets(
    case: dict[str, Any], *, outputs_root: Path
) -> dict[str, Any] | None:
    manifest_path = _artifact_path(
        str(case.get("plot_manifest_path") or ""), outputs_root=outputs_root
    )
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

    split_entries = [
        item
        for item in plot_entries
        if "/overview/" not in str(item.get("path_rel") or "")
    ]
    preview_entry = next(
        (
            item
            for item in split_entries
            if str(item.get("filename") or "") == "spatial_trajectory_comparison.png"
        ),
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
            _artifact_path(
                str(case.get("plot_bundle_dir") or ""), outputs_root=outputs_root
            ),
            outputs_root=outputs_root,
        ),
        "events": list(manifest_payload.get("events") or []),
        "target": dict(manifest_payload.get("target") or {}),
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _stddev(values: list[float]) -> float | None:
    if not values:
        return None
    mean = _mean(values)
    if mean is None:
        return None
    return math.sqrt(sum((value - mean) ** 2 for value in values) / float(len(values)))


def _successful_run_metric_values(
    runs: list[dict[str, Any]], field: str
) -> list[float]:
    values: list[float] = []
    for run in runs:
        record = dict(run.get("record") or {})
        if not bool(record.get("success", False)):
            continue
        raw_value = record.get(field)
        try:
            values.append(float(raw_value))
        except (TypeError, ValueError):
            continue
    return values


def _summary_metric_stat(
    summary_row: dict[str, Any],
    field: str,
    *,
    stat: str = "mean",
    scope: str = "success",
) -> float | None:
    metric = _summary_metric(summary_row, field, scope=scope)
    if stat != "count" and int(metric.get("count", 0) or 0) <= 0:
        return None
    raw_value = metric.get(stat)
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _scenario_metric_stat(
    summary_row: dict[str, Any],
    runs: list[dict[str, Any]],
    field: str,
    *,
    stat: str = "mean",
) -> float | None:
    summary_value = _summary_metric_stat(summary_row, field, stat=stat, scope="success")
    if summary_value is not None:
        return summary_value
    values = _successful_run_metric_values(runs, field)
    if not values:
        return None
    if stat == "mean":
        return _mean(values)
    if stat == "stddev":
        return _stddev(values)
    if stat == "max":
        return max(values)
    if stat == "min":
        return min(values)
    if stat == "count":
        return float(len(values))
    return None


def _scenario_summary_data(
    summary_row: dict[str, Any], runs: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "runs": int(summary_row.get("runs", len(runs)) or len(runs)),
        "successes": int(
            summary_row.get(
                "successes",
                sum(1 for run in runs if bool(run["record"].get("success", False))),
            )
            or 0
        ),
        "crashed": int(
            summary_row.get(
                "crashed",
                sum(
                    1
                    for run in runs
                    if str(run["record"].get("state") or "").strip().lower()
                    == "crashed"
                ),
            )
            or 0
        ),
        "success_rate": float(
            summary_row.get(
                "success_rate",
                (
                    sum(1 for run in runs if bool(run["record"].get("success", False)))
                    / float(len(runs))
                )
                if runs
                else 0.0,
            )
            or 0.0
        ),
        "fuel_mean": _scenario_metric_stat(summary_row, runs, "fuel_consumed"),
        "fuel_stddev": _scenario_metric_stat(
            summary_row, runs, "fuel_consumed", stat="stddev"
        ),
        "time_mean": _scenario_metric_stat(summary_row, runs, "time"),
        "time_stddev": _scenario_metric_stat(summary_row, runs, "time", stat="stddev"),
        "offset_mean": _scenario_metric_stat(summary_row, runs, "landing_offset"),
        "offset_stddev": _scenario_metric_stat(
            summary_row, runs, "landing_offset", stat="stddev"
        ),
        "ref_gap_mean": _scenario_metric_stat(summary_row, runs, "trace_ref_gap_mean"),
        "ref_gap_stddev": _scenario_metric_stat(
            summary_row, runs, "trace_ref_gap_mean", stat="stddev"
        ),
        "ref_peak_max": _scenario_metric_stat(
            summary_row, runs, "trace_ref_gap_max", stat="max"
        ),
        "total_ms_mean": _scenario_metric_stat(
            summary_row, runs, "bot_profile_total_ms_per_tick"
        ),
    }


def _new_scenario_tree_node(selector: str, *, level: str, depth: int) -> dict[str, Any]:
    return {
        "selector": selector,
        "level": level,
        "depth": depth,
        "runs": [],
        "summary_row": {},
        "children_map": {},
    }


def _leaf_representative_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    traced = [run for run in runs if run.get("trace_path_rel") or run.get("trace_path")]
    if not traced:
        return None
    return min(
        traced,
        key=lambda run: _scenario_representative_sort_key(
            dict(run.get("record") or {})
        ),
    )


def _find_descendant_representative_run(
    node: dict[str, Any], selector: str
) -> dict[str, Any] | None:
    if str(node.get("selector") or "") == selector:
        representative = node.get("representative_run")
        return representative if isinstance(representative, dict) else None
    for child in node.get("children") or []:
        found = _find_descendant_representative_run(child, selector)
        if found is not None:
            return found
    return None


def _preferred_representative_run(node: dict[str, Any]) -> dict[str, Any] | None:
    children = list(node.get("children") or [])
    if not children:
        return _leaf_representative_run(list(node.get("runs") or []))

    selector = str(node.get("selector") or "")
    parts = selector.split(":")
    if not parts:
        return None
    level_name = parts[0]
    scenario_path = tuple(parts[1:])
    try:
        binding = resolve_selector_binding(level_name, scenario_path=scenario_path)
    except ValueError:
        binding = None
    if binding is not None and binding.path:
        default_selector = ":".join([level_name, *binding.path])
        default_run = _find_descendant_representative_run(node, default_selector)
        if default_run is not None:
            return default_run
    for child in children:
        representative = child.get("representative_run")
        if isinstance(representative, dict):
            return representative
    return None


def _finalize_scenario_tree_node(node: dict[str, Any]) -> dict[str, Any]:
    children = sorted(
        list(dict(node.get("children_map") or {}).values()),
        key=lambda item: _selector_sort_key(str(item.get("selector") or "")),
    )
    for child in children:
        _finalize_scenario_tree_node(child)
    node["children"] = children
    node["summary"] = _scenario_summary_data(
        dict(node.get("summary_row") or {}), list(node.get("runs") or [])
    )
    node["representative_run"] = _preferred_representative_run(node)
    node.pop("children_map", None)
    return node


def _build_scenario_trees(
    *,
    runs_by_scenario: dict[str, list[dict[str, Any]]],
    summary: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    roots: dict[str, dict[str, Any]] = {}
    for scenario_selector in sorted(runs_by_scenario, key=_selector_sort_key):
        runs = list(runs_by_scenario[scenario_selector])
        tokens = scenario_selector.split(":")
        if len(tokens) < 2:
            continue
        level_name = tokens[0]
        summary_row = dict(summary.get("by_selector", {}).get(scenario_selector) or {})
        root = roots.setdefault(level_name, {"children_map": {}})
        parent_children = root["children_map"]
        for depth_index, token_count in enumerate(range(2, len(tokens) + 1)):
            prefix_selector = ":".join(tokens[:token_count])
            node = parent_children.get(prefix_selector)
            if node is None:
                node = _new_scenario_tree_node(
                    prefix_selector, level=level_name, depth=depth_index
                )
                parent_children[prefix_selector] = node
            node["runs"].extend(runs)
            if token_count == len(tokens):
                node["summary_row"] = summary_row
            parent_children = node["children_map"]

    trees_by_level: dict[str, list[dict[str, Any]]] = {}
    for level_name in sorted(roots, key=_selector_sort_key):
        top_children = sorted(
            list(dict(roots[level_name].get("children_map") or {}).values()),
            key=lambda item: _selector_sort_key(str(item.get("selector") or "")),
        )
        for child in top_children:
            _finalize_scenario_tree_node(child)
        trees_by_level[level_name] = top_children
    return trees_by_level


def _build_bundle_report_model(
    bundle: dict[str, Any], *, outputs_root: Path
) -> dict[str, Any]:
    def _build_report_block(
        payload: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        summary = dict(payload.get("summary") or {})
        records = [
            dict(item)
            for item in payload.get("records") or []
            if isinstance(item, dict)
        ]
        records.sort(
            key=lambda record: (
                _selector_sort_key(_scenario_selector_for_record(record)),
                _record_seed_sort_key(record),
                int(record.get("run_instance_id", 1) or 1),
            )
        )

        runs_by_scenario: dict[str, list[dict[str, Any]]] = {}
        runs: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        duplicate_counts: dict[str, int] = {}
        for record in records:
            selector = render_record_selector(record)
            duplicate_counts[selector] = duplicate_counts.get(selector, 0) + 1

        for record in records:
            run_selector = render_record_selector(record)
            scenario_selector = _scenario_selector_for_record(record)
            detail_rel = _record_detail_rel_path(bundle_id, record, source=source)
            trace_assets = _load_trace_asset_paths(record, outputs_root=outputs_root)
            run_info = {
                "selector": run_selector,
                "scenario_selector": scenario_selector,
                "record": record,
                "detail_rel": detail_rel,
                "run_key": str(record.get("run_key") or run_selector),
                "run_instance_id": int(record.get("run_instance_id", 1) or 1),
                "duplicate_count": duplicate_counts.get(run_selector, 1),
                "report_source": source,
                **trace_assets,
            }
            runs_by_scenario.setdefault(scenario_selector, []).append(run_info)
            runs.append(run_info)
            if not bool(record.get("success", False)):
                failures.append(run_info)

        return {
            "scenario_trees_by_level": _build_scenario_trees(
                runs_by_scenario=runs_by_scenario,
                summary=summary,
            ),
            "failures": sorted(
                failures,
                key=lambda item: _selector_sort_key(str(item.get("selector") or "")),
            ),
            "runs": runs,
        }

    def _index_scenario_trees(
        trees_by_level: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}

        def _visit(node: dict[str, Any]) -> None:
            selector = str(node.get("selector") or "")
            if selector:
                out[selector] = node
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _visit(child)

        for nodes in trees_by_level.values():
            for node in nodes:
                if isinstance(node, dict):
                    _visit(node)
        return out

    benchmark = dict(bundle.get("benchmark") or {})
    bundle_id = str(bundle.get("bundle_id") or "bundle")
    candidate_payload = {
        "summary": dict(dict(benchmark.get("candidate") or {}).get("summary") or {}),
        "records": [
            dict(item)
            for item in benchmark.get("records") or []
            if isinstance(item, dict)
        ],
    }
    candidate_report = _build_report_block(candidate_payload, source="candidate")

    baseline_payload: dict[str, Any] | None = None
    baseline_json_path = _baseline_candidate_json_path(
        bundle, outputs_root=outputs_root
    )
    if baseline_json_path is not None and baseline_json_path.exists():
        loaded_payload = load_json(baseline_json_path)
        if isinstance(loaded_payload, dict):
            baseline_payload = loaded_payload

    baseline_report = (
        _build_report_block(baseline_payload, source="baseline")
        if baseline_payload is not None
        else None
    )
    return {
        "scenario_trees_by_level": candidate_report["scenario_trees_by_level"],
        "baseline_scenario_index": (
            _index_scenario_trees(
                dict(baseline_report.get("scenario_trees_by_level") or {})
            )
            if baseline_report is not None
            else {}
        ),
        "failures": list(candidate_report.get("failures") or []),
        "runs": list(candidate_report.get("runs") or [])
        + list((baseline_report or {}).get("runs") or []),
    }


def _render_inline_list(items: list[str], *, code: bool = False) -> str:
    if not items:
        return '<span class="muted">(none)</span>'
    rendered: list[str] = []
    for item in items:
        token = html.escape(str(item))
        rendered.append(f"<code>{token}</code>" if code else token)
    return ", ".join(rendered)


def _render_text_list(items: list[str], *, code: bool = False) -> str:
    if not items:
        return '<p class="muted">(none)</p>'
    rows = []
    for item in items:
        value = html.escape(str(item))
        if code:
            value = f"<code>{value}</code>"
        rows.append(f"<li>{value}</li>")
    return f"<ul>{''.join(rows)}</ul>"


def _format_mean_stddev(mean_value: Any, stddev_value: Any, *, digits: int = 2) -> str:
    mean_number = _format_float(mean_value, digits)
    if mean_number == "-":
        return "-"
    stddev_number = _format_float(stddev_value, digits)
    if stddev_number == "-":
        return mean_number
    return f"{mean_number} ± {stddev_number}"


def _format_mean_percent_spread(
    mean_value: Any,
    stddev_value: Any,
    *,
    digits: int = 2,
    percent_digits: int = 1,
) -> str:
    try:
        mean_number = float(mean_value)
    except (TypeError, ValueError):
        return "-"
    try:
        stddev_number = float(stddev_value)
    except (TypeError, ValueError):
        return _format_float(mean_number, digits)
    if abs(mean_number) <= 1e-9:
        return _format_float(mean_number, digits)
    spread_percent = 100.0 * abs(stddev_number) / abs(mean_number)
    return f"{mean_number:.{digits}f} ± {spread_percent:.{percent_digits}f}%"


def _format_percent_spread(
    mean_value: Any,
    stddev_value: Any,
    *,
    digits: int = 1,
) -> str:
    spread_percent = _percent_spread_value(mean_value, stddev_value)
    if spread_percent is None:
        return "-"
    return f"{spread_percent:.{digits}f}%"


def _percent_spread_value(mean_value: Any, stddev_value: Any) -> float | None:
    try:
        mean_number = float(mean_value)
        stddev_number = float(stddev_value)
    except (TypeError, ValueError):
        return None
    if abs(mean_number) <= 1e-9:
        return None
    return 100.0 * abs(stddev_number) / abs(mean_number)


def _summary_value_cell_html(
    mean_value: Any,
    stddev_value: Any,
    *,
    show_spread: bool,
    digits: int = 2,
    percent_digits: int = 1,
) -> str:
    mean_text = _format_float(mean_value, digits)
    if not show_spread:
        return html.escape(mean_text)
    return html.escape(
        _format_mean_percent_spread(
            mean_value,
            stddev_value,
            digits=digits,
            percent_digits=percent_digits,
        )
    )


def _render_metric_stack(items: list[tuple[str, str]]) -> str:
    rows: list[str] = []
    for label, value in items:
        if str(value).strip() in {"", "-"}:
            continue
        rows.append(
            '<div class="metric-line">'
            f'<span class="metric-key">{html.escape(label)}</span>'
            f"<span>{html.escape(value)}</span>"
            "</div>"
        )
    if not rows:
        return '<span class="muted">-</span>'
    return f'<div class="metric-stack">{"".join(rows)}</div>'


def _render_run_preview_cell(
    run: dict[str, Any] | None, *, bundle_dir: Path, outputs_root: Path
) -> str:
    if not isinstance(run, dict):
        return '<span class="muted">expand</span>'
    preview_href = _href_from(
        bundle_dir,
        str(run.get("preview_path_rel") or ""),
        outputs_root=outputs_root,
    )
    detail_href = _href_from(
        bundle_dir,
        str(run.get("detail_rel") or ""),
        outputs_root=outputs_root,
    )
    if not preview_href or not detail_href:
        return '<span class="muted">expand</span>'
    alt_text = html.escape(
        str(run.get("selector") or run.get("scenario_selector") or "run")
    )
    return (
        f'<a class="table-preview" href="{html.escape(detail_href)}">'
        f'<img src="{html.escape(preview_href)}" alt="{alt_text}">'
        "</a>"
    )


def _scenario_metric_cell_html(
    summary_data: dict[str, Any], *, show_spread: bool
) -> str:
    items: list[tuple[str, str]] = [
        ("offset mean", _format_float(summary_data.get("offset_mean"), 3)),
        ("ref gap mean", _format_float(summary_data.get("ref_gap_mean"), 3)),
        ("ref peak max", _format_float(summary_data.get("ref_peak_max"), 3)),
    ]
    if show_spread:
        items = [
            (
                "offset μ/σ",
                _format_mean_stddev(
                    summary_data.get("offset_mean"),
                    summary_data.get("offset_stddev"),
                    digits=3,
                ),
            ),
            (
                "ref gap μ/±%",
                _format_mean_percent_spread(
                    summary_data.get("ref_gap_mean"),
                    summary_data.get("ref_gap_stddev"),
                    digits=3,
                ),
            ),
            ("ref peak max", _format_float(summary_data.get("ref_peak_max"), 3)),
        ]
    return _render_metric_stack(items)


def _seed_metric_cell_html(record: dict[str, Any]) -> str:
    return _render_metric_stack(
        [
            ("offset", _format_float(record.get("landing_offset"), 3)),
            ("ref gap", _format_float(record.get("trace_ref_gap_mean"), 3)),
            ("ref peak", _format_float(record.get("trace_ref_gap_max"), 3)),
        ]
    )


def _tracepack_ref_label(path_rel: Any, *, fallback: Any = "") -> str:
    fallback_text = str(fallback or "").strip()
    if fallback_text:
        return fallback_text
    path_text = str(path_rel or "").strip()
    if not path_text:
        return "-"
    try:
        return Path(path_text).parent.name or "-"
    except (TypeError, ValueError):
        return "-"


def _humanize_pack_label(candidate_json_path: Path) -> str:
    stem = candidate_json_path.stem
    if stem.endswith(".tracepack"):
        stem = stem[: -len(".tracepack")]
    parts = [part for part in stem.split("_") if part]
    if not parts:
        return "Benchmark"
    mode = parts[0].replace("-", " ").title()
    if len(parts) == 1:
        return f"{mode} Benchmark"
    pack_token = parts[1]
    pack_label = " / ".join(
        token.replace("-", " ").title()
        for token in pack_token.split("-")
        if token.strip()
    )
    if not pack_label:
        return f"{mode} Benchmark"
    return f"{mode} {pack_label} Benchmark"


def _bundle_title(candidate_json_path: Path, *, compare: bool) -> str:
    suffix = "Compare" if compare else "Report"
    return f"{_humanize_pack_label(candidate_json_path)} {suffix}"


def _summary_success_text(summary: dict[str, Any]) -> str:
    runs = int(summary.get("runs", 0) or 0)
    successes = int(summary.get("successes", 0) or 0)
    if runs <= 0:
        return "-"
    return f"{successes}/{runs} ({_format_percent(summary.get('success_rate'))})"


def _summary_metric_value(
    summary: dict[str, Any],
    field: str,
    *,
    scope: str = "success",
    stat: str = "mean",
) -> Any:
    return _summary_metric(summary, field, scope=scope).get(stat)


def _summary_like_metric_value(
    summary: dict[str, Any],
    *,
    flat_key: str,
    field: str,
    scope: str = "success",
    stat: str = "mean",
) -> Any:
    if "efficiency_all" in summary or "efficiency_success" in summary:
        return _summary_metric_value(summary, field, scope=scope, stat=stat)
    return summary.get(flat_key)


def _summary_compare_delta(
    candidate_value: Any,
    baseline_value: Any,
    *,
    digits: int = 2,
) -> str:
    try:
        return f"{float(candidate_value) - float(baseline_value):+.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _summary_compare_delta_percent_points(
    candidate_value: Any,
    baseline_value: Any,
    *,
    digits: int = 2,
) -> str:
    try:
        return (
            f"{(float(candidate_value) - float(baseline_value)) * 100.0:+.{digits}f} pp"
        )
    except (TypeError, ValueError):
        return "-"


def _summary_compare_delta_count(
    candidate_value: Any,
    baseline_value: Any,
) -> str:
    try:
        return f"{int(candidate_value) - int(baseline_value):+d}"
    except (TypeError, ValueError):
        return "-"


def _load_baseline_payload(
    bundle: dict[str, Any], *, outputs_root: Path
) -> tuple[Path | None, dict[str, Any] | None]:
    baseline_json_path = _baseline_candidate_json_path(
        bundle, outputs_root=outputs_root
    )
    if baseline_json_path is None or not baseline_json_path.is_file():
        return baseline_json_path, None
    loaded = load_json(baseline_json_path)
    return baseline_json_path, loaded if isinstance(loaded, dict) else None


def _overview_diff_unavailable_cell() -> str:
    return _render_metric_stack([("status", "unavailable")])


def _overview_result_cell(summary: dict[str, Any]) -> str:
    runs = int(summary.get("runs", 0) or 0)
    successes = int(summary.get("successes", 0) or 0)
    crashes = int(summary.get("crashed", 0) or 0)
    return _render_metric_stack(
        [
            (
                "success",
                f"{successes}/{runs} ({_format_percent(summary.get('success_rate'))})",
            ),
            ("crashes", str(crashes)),
        ]
    )


def _overview_efficiency_cell(summary: dict[str, Any]) -> str:
    return _render_metric_stack(
        [
            (
                "fuel all",
                _format_float(
                    _summary_metric_value(summary, "fuel_consumed", scope="all")
                ),
            ),
            (
                "fuel success",
                _format_float(
                    _summary_metric_value(summary, "fuel_consumed", scope="success")
                ),
            ),
            (
                "time all",
                _format_float(_summary_metric_value(summary, "time", scope="all")),
            ),
            (
                "time success",
                _format_float(_summary_metric_value(summary, "time", scope="success")),
            ),
        ]
    )


def _overview_tracking_cell(summary: dict[str, Any]) -> str:
    return _render_metric_stack(
        [
            (
                "gap mean",
                _format_float(
                    _summary_metric_value(
                        summary, "trace_ref_gap_mean", scope="success"
                    ),
                    3,
                ),
            ),
            (
                "gap peak",
                _format_float(
                    _summary_metric_value(
                        summary, "trace_ref_gap_max", scope="success", stat="max"
                    ),
                    3,
                ),
            ),
        ]
    )


def _overview_compute_cell(summary: dict[str, Any]) -> str:
    return _render_metric_stack(
        [
            (
                "bot mean",
                _format_float(
                    _summary_metric_value(
                        summary, "bot_profile_total_ms_per_tick", scope="all"
                    ),
                    3,
                ),
            ),
            (
                "bot p99",
                _format_float(
                    _summary_metric_value(
                        summary, "bot_profile_total_ms_per_tick_p99", scope="all"
                    ),
                    3,
                ),
            ),
        ]
    )


def _overview_wall_clock_cell(benchmark_wall_clock_s: Any) -> str:
    return _render_metric_stack(
        [
            ("bench", _format_float(benchmark_wall_clock_s, 3)),
        ]
    )


def _overview_diff_ref_cell(compare_basis: dict[str, Any]) -> str:
    if not compare_basis:
        return '<span class="muted">current - baseline</span>'
    return _render_metric_stack(
        [
            ("basis", str(compare_basis.get("mode") or "-")),
            (
                "shared runs",
                str(int(compare_basis.get("shared_runs", 0) or 0)),
            ),
            (
                "cur-only",
                str(int(compare_basis.get("candidate_only_runs", 0) or 0)),
            ),
            (
                "base-only",
                str(int(compare_basis.get("baseline_only_runs", 0) or 0)),
            ),
        ]
    )


def _compare_compute_delta(compare: dict[str, Any], metric: str) -> Any:
    compute = dict(compare.get("compute") or {})
    deltas = dict(compute.get("deltas") or {})
    return dict(deltas.get(metric) or {}).get("delta_abs")


def _overview_diff_result_cell(
    candidate_summary: dict[str, Any], baseline_summary: dict[str, Any]
) -> str:
    return _render_metric_stack(
        [
            (
                "success rate",
                _summary_compare_delta_percent_points(
                    candidate_summary.get("success_rate"),
                    baseline_summary.get("success_rate"),
                ),
            ),
            (
                "crashes",
                _summary_compare_delta_count(
                    candidate_summary.get("crashed", 0),
                    baseline_summary.get("crashed", 0),
                ),
            ),
        ]
    )


def _overview_diff_efficiency_cell(
    candidate_summary: dict[str, Any], baseline_summary: dict[str, Any]
) -> str:
    return _render_metric_stack(
        [
            (
                "fuel all",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="fuel_mean_all",
                        field="fuel_consumed",
                        scope="all",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="fuel_mean_all",
                        field="fuel_consumed",
                        scope="all",
                    ),
                ),
            ),
            (
                "fuel success",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="fuel_mean_success",
                        field="fuel_consumed",
                        scope="success",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="fuel_mean_success",
                        field="fuel_consumed",
                        scope="success",
                    ),
                ),
            ),
            (
                "time all",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="time_mean_all",
                        field="time",
                        scope="all",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="time_mean_all",
                        field="time",
                        scope="all",
                    ),
                ),
            ),
            (
                "time success",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="time_mean_success",
                        field="time",
                        scope="success",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="time_mean_success",
                        field="time",
                        scope="success",
                    ),
                ),
            ),
        ]
    )


def _overview_diff_tracking_cell(
    candidate_summary: dict[str, Any], baseline_summary: dict[str, Any]
) -> str:
    return _render_metric_stack(
        [
            (
                "gap mean",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="ref_gap_mean_mean_success",
                        field="trace_ref_gap_mean",
                        scope="success",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="ref_gap_mean_mean_success",
                        field="trace_ref_gap_mean",
                        scope="success",
                    ),
                    digits=3,
                ),
            ),
            (
                "gap peak",
                _summary_compare_delta(
                    _summary_like_metric_value(
                        candidate_summary,
                        flat_key="ref_gap_peak_max_success",
                        field="trace_ref_gap_max",
                        scope="success",
                        stat="max",
                    ),
                    _summary_like_metric_value(
                        baseline_summary,
                        flat_key="ref_gap_peak_max_success",
                        field="trace_ref_gap_max",
                        scope="success",
                        stat="max",
                    ),
                    digits=3,
                ),
            ),
        ]
    )


def _overview_diff_compute_cell(
    candidate_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    compare: dict[str, Any],
) -> str:
    mean_delta = _compare_compute_delta(compare, "bot_profile_total_ms_per_tick")
    p99_delta = _compare_compute_delta(compare, "bot_profile_total_ms_per_tick_p99")
    if mean_delta is None:
        candidate_mean = _summary_metric_value(
            candidate_summary, "bot_profile_total_ms_per_tick", scope="all"
        )
        baseline_mean = _summary_metric_value(
            baseline_summary, "bot_profile_total_ms_per_tick", scope="all"
        )
        if candidate_mean is not None and baseline_mean is not None:
            mean_delta = float(candidate_mean) - float(baseline_mean)
    if p99_delta is None:
        candidate_p99 = _summary_metric_value(
            candidate_summary, "bot_profile_total_ms_per_tick_p99", scope="all"
        )
        baseline_p99 = _summary_metric_value(
            baseline_summary, "bot_profile_total_ms_per_tick_p99", scope="all"
        )
        if candidate_p99 is not None and baseline_p99 is not None:
            p99_delta = float(candidate_p99) - float(baseline_p99)
    return _render_metric_stack(
        [
            (
                "bot mean",
                _format_float(mean_delta, 3) if mean_delta is not None else "-",
            ),
            ("bot p99", _format_float(p99_delta, 3) if p99_delta is not None else "-"),
        ]
    )


def _overview_diff_wall_clock_cell(
    candidate_wall_clock_s: Any, baseline_wall_clock_s: Any
) -> str:
    try:
        if candidate_wall_clock_s is None or baseline_wall_clock_s is None:
            raise TypeError
        delta = float(candidate_wall_clock_s) - float(baseline_wall_clock_s)
    except (TypeError, ValueError):
        return _overview_diff_unavailable_cell()
    return _render_metric_stack([("bench", _format_float(delta, 3))])


def _render_overview_section(bundle: dict[str, Any], *, outputs_root: Path) -> str:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    compare = dict(bundle.get("compare") or {})
    timing = dict(bundle.get("timing") or {})
    candidate_summary = dict(candidate.get("summary") or {})
    candidate_json_rel = str(candidate.get("json_path") or "")
    candidate_wall_clock_s = candidate.get("benchmark_wall_clock_s")
    if candidate_wall_clock_s is None:
        candidate_wall_clock_s = timing.get("benchmark_wall_clock_s")

    rows: list[tuple[str, list[str]]] = [
        (
            "summary-row",
            [
                '<span class="row-tag candidate">current</span>',
                f"<code>{html.escape(_tracepack_ref_label(candidate_json_rel, fallback=compare.get('candidate_commit')))}</code>",
                _overview_result_cell(candidate_summary),
                _overview_wall_clock_cell(candidate_wall_clock_s),
                _overview_efficiency_cell(candidate_summary),
                _overview_tracking_cell(candidate_summary),
                _overview_compute_cell(candidate_summary),
            ],
        )
    ]

    baseline_json_path, baseline_payload = _load_baseline_payload(
        bundle, outputs_root=outputs_root
    )
    if compare and baseline_payload is not None:
        baseline_summary = dict(baseline_payload.get("summary") or {})
        baseline_wall_clock_s = baseline_payload.get("benchmark_wall_clock_s")
        compare_candidate_summary = dict(compare.get("summary_candidate") or {})
        compare_baseline_summary = dict(compare.get("summary_baseline") or {})
        compare_basis = dict(compare.get("compare_basis") or {})
        compare_available = str(
            compare_basis.get("mode") or ""
        ).strip() != "no_shared_runs" and bool(compare.get("summary_available", True))
        baseline_json_rel = _rel_to_outputs(
            baseline_json_path, outputs_root=outputs_root
        )
        rows.append(
            (
                "baseline-summary-row baseline-row",
                [
                    '<span class="row-tag baseline">baseline</span>',
                    f"<code>{html.escape(_tracepack_ref_label(baseline_json_rel, fallback=compare.get('baseline_commit')))}</code>",
                    _overview_result_cell(baseline_summary),
                    _overview_wall_clock_cell(baseline_wall_clock_s),
                    _overview_efficiency_cell(baseline_summary),
                    _overview_tracking_cell(baseline_summary),
                    _overview_compute_cell(baseline_summary),
                ],
            )
        )
        rows.append(
            (
                "diff-summary-row",
                [
                    '<span class="row-tag diff">diff</span>',
                    _overview_diff_ref_cell(compare_basis),
                    (
                        _overview_diff_result_cell(
                            compare_candidate_summary or candidate_summary,
                            compare_baseline_summary or baseline_summary,
                        )
                        if compare_available
                        else _overview_diff_unavailable_cell()
                    ),
                    _overview_diff_wall_clock_cell(
                        candidate_wall_clock_s, baseline_wall_clock_s
                    ),
                    (
                        _overview_diff_efficiency_cell(
                            compare_candidate_summary or candidate_summary,
                            compare_baseline_summary or baseline_summary,
                        )
                        if compare_available
                        else _overview_diff_unavailable_cell()
                    ),
                    (
                        _overview_diff_tracking_cell(
                            compare_candidate_summary or candidate_summary,
                            compare_baseline_summary or baseline_summary,
                        )
                        if compare_available
                        else _overview_diff_unavailable_cell()
                    ),
                    (
                        _overview_diff_compute_cell(
                            compare_candidate_summary or candidate_summary,
                            compare_baseline_summary or baseline_summary,
                            compare,
                        )
                        if compare_available
                        else _overview_diff_unavailable_cell()
                    ),
                ],
            )
        )

    return (
        '<div class="header-overview">'
        "<h2>Overview</h2>"
        '<div class="table-wrap">'
        + _render_table_with_row_classes(
            [
                "Pack",
                "Ref",
                "Result",
                "Wall Clock",
                "Efficiency",
                "Tracking",
                "Compute",
            ],
            rows,
            table_class="summary-table",
        )
        + "</div>"
        "</div>"
    )


def _render_context_section(
    intent: dict[str, Any],
    *,
    candidate: dict[str, Any],
    compare: dict[str, Any],
) -> str:
    if not intent and not candidate and not compare:
        return ""
    compare_basis = dict(compare.get("compare_basis") or {})
    compare_basis_text = ""
    if compare_basis:
        compare_basis_text = (
            f"{str(compare_basis.get('mode') or '-')} "
            f"(shared {int(compare_basis.get('shared_runs', 0) or 0)}, "
            f"current-only {int(compare_basis.get('candidate_only_runs', 0) or 0)}, "
            f"baseline-only {int(compare_basis.get('baseline_only_runs', 0) or 0)})"
        )
    rows = [
        ["Goal", html.escape(str(intent.get("goal_summary") or "-"))],
        ["Request Source", html.escape(str(intent.get("request_source") or "-"))],
        [
            "Tracepack Mode",
            html.escape("compare" if compare else "single"),
        ],
        *(
            [["Compare Basis", html.escape(compare_basis_text)]]
            if compare_basis_text
            else []
        ),
        [
            "Touched Areas",
            _render_inline_list(list(intent.get("touched_areas") or []), code=True),
        ],
        [
            "Changed Files",
            _render_inline_list(
                list(intent.get("changed_files") or [])[:10], code=True
            ),
        ],
    ]
    details = _render_table(["Field", "Value"], rows)
    conversation = list(intent.get("conversation_context") or [])
    assumptions = list(intent.get("assumptions") or [])
    sections = [
        "<section>",
        "<h2>Context</h2>",
        details,
    ]
    if conversation:
        sections.append("<h3>Conversation Context</h3>")
        sections.append(_render_text_list(conversation))
    if assumptions:
        sections.append("<h3>Assumptions</h3>")
        sections.append(_render_text_list(assumptions))
    sections.append("</section>")
    return "".join(sections)


def _verdict_banner_class(verdict: str) -> str:
    verdict_key = str(verdict).strip().lower()
    if verdict_key == "improvement":
        return "ok"
    if verdict_key in {"regression", "investigate"}:
        return "bad"
    return "neutral"


def _render_outcome_section(analysis: dict[str, Any]) -> str:
    if not analysis:
        return ""
    verdict = str(analysis.get("verdict") or "-")
    sections = [
        "<section>",
        "<h2>Outcome</h2>",
        f'<p class="banner {_verdict_banner_class(verdict)}">{html.escape(verdict)}</p>',
        f"<p>{html.escape(str(analysis.get('summary') or '-'))}</p>",
    ]
    evidence = list(analysis.get("measured_evidence") or [])
    if evidence:
        sections.append("<h3>Measured Evidence</h3>")
        sections.append(_render_text_list(evidence, code=True))
    sections.append("</section>")
    return "".join(sections)


def _render_analysis_section(analysis: dict[str, Any]) -> str:
    if not analysis:
        return ""
    likely_causes = list(analysis.get("likely_causes") or [])
    follow_ups = list(analysis.get("follow_ups") or [])
    sections = [
        "<section>",
        "<h2>Analysis</h2>",
        f"<p><strong>Confidence:</strong> {html.escape(str(analysis.get('confidence') or '-'))}</p>",
    ]
    if likely_causes:
        sections.append("<h3>Likely Causes</h3>")
        sections.append(_render_text_list(likely_causes))
    if follow_ups:
        sections.append("<h3>Suggested Follow-Ups</h3>")
        sections.append(_render_text_list(follow_ups, code=True))
    sections.append("</section>")
    return "".join(sections)


def _render_scenario_sections(
    report: dict[str, Any],
    *,
    bundle_dir: Path,
    outputs_root: Path,
) -> str:
    table_counter = 0
    baseline_scenario_index = dict(report.get("baseline_scenario_index") or {})

    def _summary_row_html(
        selector: str,
        summary_data: dict[str, Any],
        *,
        depth: int,
        parent_group_id: str | None,
        group_id: str | None,
        expandable: bool,
        show_spread: bool,
        representative_run: dict[str, Any] | None,
        tone: str,
        label: str,
    ) -> str:
        hidden_attr = " hidden" if parent_group_id else ""
        parent_attr = (
            f' data-parent="{html.escape(parent_group_id)}"' if parent_group_id else ""
        )
        group_attr = f' data-group="{html.escape(group_id)}"' if group_id else ""
        expanded_attr = ' aria-expanded="false"' if expandable else ""
        tabindex_attr = ' tabindex="0"' if expandable else ""
        row_class = "scenario-row" if tone == "candidate" else "baseline-scenario-row"
        preview_cell = _render_run_preview_cell(
            representative_run, bundle_dir=bundle_dir, outputs_root=outputs_root
        )
        expander_html = (
            '<span class="expander">+</span>'
            if expandable
            else '<span class="expander muted">•</span>'
        )
        return (
            f'<tr class="{row_class} {tone}-row"'
            f"{hidden_attr}{parent_attr}{group_attr}{expanded_attr}{tabindex_attr}>"
            f'<td class="tree-label" style="--depth: {depth};"><span class="row-tag {tone}">{html.escape(label)}</span>{expander_html}{html.escape(selector)}</td>'
            f"<td>{html.escape(str(int(summary_data.get('successes', 0) or 0)) + '/' + str(int(summary_data.get('runs', 0) or 0)))}</td>"
            f"<td>{_summary_value_cell_html(summary_data.get('fuel_mean'), summary_data.get('fuel_stddev'), show_spread=show_spread)}</td>"
            f"<td>{_summary_value_cell_html(summary_data.get('time_mean'), summary_data.get('time_stddev'), show_spread=show_spread)}</td>"
            f"<td>{_scenario_metric_cell_html(summary_data, show_spread=show_spread)}</td>"
            f"<td>{preview_cell}</td>"
            "</tr>"
        )

    def _seed_row_html(
        run: dict[str, Any],
        *,
        depth: int,
        group_id: str,
        tone: str,
        label: str,
    ) -> str:
        record = dict(run.get("record") or {})
        detail_href = (
            _href_from(
                bundle_dir,
                str(run.get("detail_rel") or ""),
                outputs_root=outputs_root,
            )
            or "#"
        )
        preview_href = _href_from(
            bundle_dir,
            str(run.get("preview_path_rel") or ""),
            outputs_root=outputs_root,
        )
        preview_cell = '<span class="muted">no plot</span>'
        if preview_href:
            preview_cell = (
                f'<a class="table-preview" href="{html.escape(detail_href)}">'
                f'<img src="{html.escape(preview_href)}" alt="{html.escape(str(run.get("selector") or "run"))}">'
                "</a>"
            )
        metric_cell = _seed_metric_cell_html(record)
        seed_label = (
            f"seed {record.get('seed') if record.get('seed') is not None else '-'}"
        )
        if int(run.get("duplicate_count", 1) or 1) > 1:
            seed_label = f"{seed_label} #{int(run.get('run_instance_id', 1) or 1)}"
        row_class = "seed-row" if tone == "candidate" else "seed-row baseline-seed-row"
        return (
            f'<tr class="{row_class} {"baseline-row" if tone == "baseline" else ""}" hidden'
            f' data-parent="{html.escape(group_id)}">'
            f'<td class="tree-label seed-label" style="--depth: {depth + 1};"><span class="row-tag {tone}">{html.escape(label)}</span>{html.escape(str(seed_label))}</td>'
            f"<td>{html.escape(str(record.get('state') or ''))}</td>"
            f"<td>{html.escape(_format_float(record.get('fuel_consumed'), 3))}</td>"
            f"<td>{html.escape(_format_float(record.get('time'), 3))}</td>"
            f"<td>{metric_cell}</td>"
            f"<td>{preview_cell}</td>"
            "</tr>"
        )

    def _render_tree_rows(
        node: dict[str, Any], *, parent_group_id: str | None
    ) -> list[str]:
        selector = str(node.get("selector") or "")
        group_id = _sanitize_token(selector)
        depth = int(node.get("depth", 0) or 0)
        summary_data = dict(node.get("summary") or {})
        children = list(node.get("children") or [])
        show_spread = not children
        rows = [
            _summary_row_html(
                selector,
                summary_data,
                depth=depth,
                parent_group_id=parent_group_id,
                group_id=group_id,
                expandable=bool(children) or bool(node.get("runs") or []),
                show_spread=show_spread,
                representative_run=(
                    node.get("representative_run")
                    if isinstance(node.get("representative_run"), dict)
                    else None
                ),
                tone="candidate",
                label="cur",
            )
        ]
        baseline_node = baseline_scenario_index.get(selector)
        if isinstance(baseline_node, dict):
            rows.append(
                _summary_row_html(
                    selector,
                    dict(baseline_node.get("summary") or {}),
                    depth=depth,
                    parent_group_id=parent_group_id,
                    group_id=None,
                    expandable=False,
                    show_spread=show_spread,
                    representative_run=(
                        baseline_node.get("representative_run")
                        if isinstance(baseline_node.get("representative_run"), dict)
                        else None
                    ),
                    tone="baseline",
                    label="base",
                )
            )
        if children:
            for child in children:
                rows.extend(_render_tree_rows(child, parent_group_id=group_id))
            return rows

        baseline_runs_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        if isinstance(baseline_node, dict):
            for baseline_run in baseline_node.get("runs") or []:
                if not isinstance(baseline_run, dict):
                    continue
                key = (
                    str(baseline_run.get("selector") or ""),
                    int(baseline_run.get("run_instance_id", 1) or 1),
                )
                baseline_runs_by_key[key] = baseline_run
        matched_baseline_keys: set[tuple[str, int]] = set()

        for run in node.get("runs") or []:
            if not isinstance(run, dict):
                continue
            rows.append(
                _seed_row_html(
                    run,
                    depth=depth,
                    group_id=group_id,
                    tone="candidate",
                    label="cur",
                )
            )
            baseline_key = (
                str(run.get("selector") or ""),
                int(run.get("run_instance_id", 1) or 1),
            )
            baseline_run = baseline_runs_by_key.get(baseline_key)
            if baseline_run is not None:
                matched_baseline_keys.add(baseline_key)
                rows.append(
                    _seed_row_html(
                        baseline_run,
                        depth=depth,
                        group_id=group_id,
                        tone="baseline",
                        label="base",
                    )
                )

        for baseline_key in sorted(
            (key for key in baseline_runs_by_key if key not in matched_baseline_keys),
            key=lambda item: (_selector_sort_key(item[0]), item[1]),
        ):
            rows.append(
                _seed_row_html(
                    baseline_runs_by_key[baseline_key],
                    depth=depth,
                    group_id=group_id,
                    tone="baseline",
                    label="base",
                )
            )
        return rows

    sections: list[str] = []
    for level_name in sorted(report["scenario_trees_by_level"], key=_selector_sort_key):
        table_counter += 1
        table_id = f"scenario-table-{table_counter}"
        row_blocks: list[str] = []
        for node in report["scenario_trees_by_level"][level_name]:
            row_blocks.extend(_render_tree_rows(node, parent_group_id=None))
        controls: list[str] = []
        if baseline_scenario_index:
            controls.append(
                f'<button type="button" class="table-button" data-action="toggle-baseline" data-target="{html.escape(table_id)}">Hide Baseline</button>'
            )
        controls.extend(
            [
                f'<button type="button" class="table-button" data-action="expand-scenarios" data-target="{html.escape(table_id)}">Expand Scenarios</button>',
                f'<button type="button" class="table-button" data-action="collapse-scenarios" data-target="{html.escape(table_id)}">Collapse Scenarios</button>',
                f'<button type="button" class="table-button" data-action="expand" data-target="{html.escape(table_id)}">Expand All</button>',
                f'<button type="button" class="table-button" data-action="collapse" data-target="{html.escape(table_id)}">Collapse All</button>',
            ]
        )
        sections.append(
            "<section>"
            f"<h2>{html.escape(level_name.title())}</h2>"
            f'<div class="table-controls">{"".join(controls)}</div>'
            '<div class="table-wrap">'
            f'<table class="scenario-table" data-tree-table="{html.escape(table_id)}">'
            "<thead><tr><th>Selector</th><th>Status</th><th>Fuel</th><th>Time</th><th>Metric</th><th>Details</th></tr></thead>"
            f"<tbody>{''.join(row_blocks)}</tbody>"
            "</table>"
            "</div>" + "</section>"
        )
    return "".join(sections)


def _render_failure_sections(
    report: dict[str, Any],
    *,
    bundle_dir: Path,
    outputs_root: Path,
) -> str:
    failures = list(report.get("failures") or [])
    if not failures:
        return '<p class="muted">No failures in this benchmark pack.</p>'

    failures_by_level: dict[str, list[dict[str, Any]]] = {}
    for run in failures:
        selector = str(run.get("selector") or "")
        level_name = selector.split(":", 1)[0] if selector else "unknown"
        failures_by_level.setdefault(level_name, []).append(run)

    sections: list[str] = []
    for level_name in sorted(failures_by_level, key=_selector_sort_key):
        row_blocks: list[str] = []
        for run in sorted(
            failures_by_level[level_name],
            key=lambda item: _selector_sort_key(str(item.get("selector") or "")),
        ):
            record = dict(run.get("record") or {})
            detail_href = (
                _href_from(
                    bundle_dir,
                    str(run.get("detail_rel") or ""),
                    outputs_root=outputs_root,
                )
                or "#"
            )
            preview_href = _href_from(
                bundle_dir,
                str(run.get("preview_path_rel") or ""),
                outputs_root=outputs_root,
            )
            selector_label = str(run.get("selector") or "")
            if int(run.get("duplicate_count", 1) or 1) > 1:
                selector_label = (
                    f"{selector_label} #{int(run.get('run_instance_id', 1) or 1)}"
                )
            if preview_href:
                preview_cell = (
                    f'<a class="table-preview" href="{html.escape(detail_href)}">'
                    f'<img src="{html.escape(preview_href)}" alt="{html.escape(str(run.get("selector") or "run"))}">'
                    "</a>"
                )
            else:
                preview_cell = '<span class="muted">no plot</span>'

            row_blocks.append(
                '<tr class="failure-row">'
                f"<td>{html.escape(selector_label)}</td>"
                f"<td>{html.escape(str(record.get('state') or ''))}</td>"
                f"<td>{html.escape(_format_float(record.get('fuel_consumed'), 3))}</td>"
                f"<td>{html.escape(_format_float(record.get('time'), 3))}</td>"
                f"<td>{html.escape(str(record.get('failure_mode') or '-'))}</td>"
                f"<td>{preview_cell}</td>"
                "</tr>"
            )

        sections.append(
            '<div class="table-wrap">'
            f"<h3>{html.escape(level_name.title())}</h3>"
            '<table class="scenario-table">'
            "<thead><tr><th>Selector</th><th>Status</th><th>Fuel</th><th>Time</th><th>Metric</th><th>Details</th></tr></thead>"
            f"<tbody>{''.join(row_blocks)}</tbody>"
            "</table>"
            "</div>"
        )
    return "".join(sections)


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
    source = str(run.get("report_source") or "candidate")
    record = dict(run.get("record") or {})
    selector = str(run.get("selector") or "unknown")
    trace_payload = _load_trace_payload(run, outputs_root=outputs_root)
    detail_dir = (outputs_root / str(run["detail_rel"])).parent
    bundle_overview_href = _href_from(
        detail_dir, str(bundle.get("bundle_page_path") or ""), outputs_root=outputs_root
    )
    source_json_rel = candidate.get("json_path")
    source_json_label = "candidate json"
    if source == "baseline":
        baseline_json_path = _baseline_candidate_json_path(
            bundle, outputs_root=outputs_root
        )
        source_json_rel = _rel_to_outputs(baseline_json_path, outputs_root=outputs_root)
        source_json_label = "baseline json"
    candidate_href = _href_from(detail_dir, source_json_rel, outputs_root=outputs_root)
    trace_href = _href_from(
        detail_dir, str(run.get("trace_path_rel") or ""), outputs_root=outputs_root
    )
    plotly_href = str(
        dict(bundle.get("viewer_assets") or {}).get("plotly_href") or PLOTLY_CDN_URL
    )

    scenario_selector = str(run.get("scenario_selector") or "")
    scenario_runs = list(report.get("runs") or [])
    representative = next(
        (
            item
            for item in scenario_runs
            if str(item.get("scenario_selector") or "") == scenario_selector
            and str(item.get("report_source") or "candidate") == source
            and (item.get("trace_path_rel") or item.get("trace_path"))
        ),
        None,
    )
    representative_href = None
    if representative is not None and str(representative.get("run_key") or "") != str(
        run.get("run_key") or ""
    ):
        representative_href = _href_from(
            detail_dir,
            str(representative.get("detail_rel") or ""),
            outputs_root=outputs_root,
        )

    return render_trace_detail_html(
        title=f"{selector} • Pylander Run Detail",
        selector=selector,
        scenario_selector=scenario_selector,
        record=record,
        trace_payload=trace_payload,
        plotly_href=plotly_href,
        top_links=[("back", bundle_overview_href)],
        raw_links=[
            (source_json_label, candidate_href),
            ("trace json", trace_href),
            ("scenario representative detail", representative_href),
        ],
        repro_commands=[
            f"uv run python main.py plot {selector} --bot {str(record.get('bot') or 'pdg')}"
        ],
    )


def _render_bundle_html(
    bundle: dict[str, Any], *, bundle_dir: Path, outputs_root: Path
) -> str:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    compare = dict(bundle.get("compare") or {})
    intent = dict(bundle.get("intent") or {})
    analysis = dict(bundle.get("analysis") or {})
    report = _build_bundle_report_model(bundle, outputs_root=outputs_root)
    latest_href = _href_from(
        bundle_dir, bundle.get("latest_page_path"), outputs_root=outputs_root
    )
    overview_html = _render_overview_section(bundle, outputs_root=outputs_root)
    intent_html = _render_context_section(intent, candidate=candidate, compare=compare)
    analysis_html = _render_outcome_section(analysis) + _render_analysis_section(
        analysis
    )
    scenario_sections_html = _render_scenario_sections(
        report, bundle_dir=bundle_dir, outputs_root=outputs_root
    )
    failure_sections_html = _render_failure_sections(
        report, bundle_dir=bundle_dir, outputs_root=outputs_root
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(str(bundle.get("title") or "Pylander Bench Bundle"))}</title>
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
    .header-overview {{
      margin-top: 18px;
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
    .banner.neutral {{ background: rgba(87, 95, 102, 0.12); color: var(--muted); }}
    section, .plot-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 24px var(--shadow);
    }}
    .metric-stack {{
      display: grid;
      gap: 4px;
    }}
    .row-tag {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2.8rem;
      margin-right: 8px;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 700;
      line-height: 1.2;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .row-tag.candidate {{
      background: rgba(14, 107, 96, 0.12);
      color: var(--accent);
    }}
    .row-tag.baseline {{
      background: rgba(87, 95, 102, 0.12);
      color: var(--muted);
    }}
    .row-tag.diff {{
      background: rgba(199, 160, 84, 0.18);
      color: #7a5611;
    }}
    .metric-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      line-height: 1.35;
    }}
    .metric-key {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }}
    .value {{
      font-size: 1.15rem;
      margin-top: 6px;
      line-height: 1.35;
      word-break: break-word;
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
    .nav-button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      background: rgba(14, 107, 96, 0.08);
      color: var(--accent);
      border-radius: 999px;
      padding: 8px 14px;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
    }}
    .nav-button:hover {{
      background: rgba(14, 107, 96, 0.14);
      text-decoration: none;
    }}
    .header-actions {{
      display: flex;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .table-wrap {{ overflow-x: auto; }}
    .summary-table {{
      width: 100%;
      min-width: 920px;
    }}
    .summary-row {{
      background: rgba(14, 107, 96, 0.10);
    }}
    .baseline-summary-row {{
      background: rgba(87, 95, 102, 0.16);
    }}
    .diff-summary-row {{
      background: rgba(199, 160, 84, 0.12);
    }}
    .table-controls {{
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .table-button {{
      border: 1px solid var(--line);
      background: rgba(14, 107, 96, 0.08);
      color: var(--accent);
      border-radius: 999px;
      padding: 6px 12px;
      font: inherit;
      cursor: pointer;
    }}
    .table-button:hover {{
      background: rgba(14, 107, 96, 0.14);
    }}
    .scenario-table {{
      width: 100%;
      min-width: 860px;
    }}
    .scenario-row {{
      cursor: pointer;
      background: rgba(14, 107, 96, 0.10);
    }}
    .baseline-scenario-row {{
      background: rgba(87, 95, 102, 0.16);
    }}
    .failure-row {{
      background: rgba(142, 59, 46, 0.05);
    }}
    .scenario-row:hover {{
      background: rgba(14, 107, 96, 0.16);
    }}
    .baseline-scenario-row:hover {{
      background: rgba(87, 95, 102, 0.22);
    }}
    .scenario-row td:first-child {{
      font-weight: 700;
    }}
    .baseline-scenario-row td:first-child {{
      font-weight: 700;
    }}
    .tree-label {{
      padding-left: calc(10px + var(--depth, 0) * 22px);
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
      background: rgba(255, 248, 233, 0.92);
    }}
    .baseline-seed-row {{
      background: rgba(219, 225, 230, 0.78);
    }}
    .scenario-table.baseline-hidden .baseline-row {{
      display: none;
    }}
    .seed-label {{
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
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
    li + li {{
      margin-top: 6px;
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
      {f'<div class="header-actions"><a class="nav-button" href="{html.escape(latest_href)}">latest</a></div>' if latest_href else ""}
      <h1>{html.escape(str(bundle.get("title") or "Pylander Bench Bundle"))}</h1>
      {overview_html}
    </header>

    {intent_html}
    {analysis_html}

    {scenario_sections_html}

    <section>
      <h2>Failures</h2>
      {failure_sections_html}
    </section>
  </main>
  <script>
    const rowsForTable = (table) => Array.from(table.querySelectorAll("tr.scenario-row, tr.baseline-scenario-row, tr.seed-row"));
    const childRows = (table, group) => Array.from(table.querySelectorAll(`tr[data-parent="${{group}}"]`));
    const scenarioChildRows = (table, group) => childRows(table, group).filter((row) => row.classList.contains("scenario-row"));

    const collapseDescendants = (table, group) => {{
      childRows(table, group).forEach((child) => {{
        child.hidden = true;
        if (child.dataset.group) {{
          child.setAttribute("aria-expanded", "false");
          collapseDescendants(table, child.dataset.group);
        }}
      }});
    }};

    const toggleScenarioRows = (row) => {{
      const table = row.closest("table");
      if (!table) return;
      const group = row.dataset.group;
      if (!group) return;
      const expanded = row.getAttribute("aria-expanded") === "true";
      if (expanded) {{
        row.setAttribute("aria-expanded", "false");
        collapseDescendants(table, group);
        return;
      }}
      row.setAttribute("aria-expanded", "true");
      childRows(table, group).forEach((child) => {{
        child.hidden = false;
      }});
    }};

    const expandScenarios = (table) => {{
      rowsForTable(table).forEach((row) => {{
        if (row.classList.contains("scenario-row") || row.classList.contains("baseline-scenario-row")) {{
          row.hidden = false;
          if (row.classList.contains("scenario-row")) {{
            row.setAttribute(
              "aria-expanded",
              scenarioChildRows(table, row.dataset.group || "").length > 0 ? "true" : "false",
            );
          }}
          return;
        }}
        row.hidden = true;
      }});
    }};

    const collapseScenarios = (table) => {{
      rowsForTable(table).forEach((row) => {{
        if (row.classList.contains("scenario-row") || row.classList.contains("baseline-scenario-row")) {{
          if (row.classList.contains("scenario-row")) {{
            row.setAttribute("aria-expanded", "false");
          }}
          row.hidden = Boolean(row.dataset.parent);
          return;
        }}
        row.hidden = true;
      }});
    }};

    const expandAll = (table) => {{
      rowsForTable(table).forEach((row) => {{
        row.hidden = false;
        if (row.classList.contains("scenario-row")) {{
          row.setAttribute("aria-expanded", "true");
        }}
      }});
    }};

    const collapseAll = (table) => {{
      rowsForTable(table).forEach((row) => {{
        if (row.classList.contains("scenario-row")) {{
          row.setAttribute("aria-expanded", "false");
        }}
        if (row.dataset.parent) {{
          row.hidden = true;
        }}
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

    document.querySelectorAll(".table-button").forEach((button) => {{
      button.addEventListener("click", () => {{
        const target = button.dataset.target;
        if (!target) return;
        const table = document.querySelector(`table[data-tree-table="${{target}}"]`);
        if (!table) return;
        if (button.dataset.action === "toggle-baseline") {{
          table.classList.toggle("baseline-hidden");
          button.textContent = table.classList.contains("baseline-hidden")
            ? "Show Baseline"
            : "Hide Baseline";
        }} else if (button.dataset.action === "expand-scenarios") {{
          expandScenarios(table);
        }} else if (button.dataset.action === "collapse-scenarios") {{
          collapseScenarios(table);
        }} else if (button.dataset.action === "expand") {{
          expandAll(table);
        }} else {{
          collapseAll(table);
        }}
      }});
    }});

    document.querySelectorAll(".scenario-table").forEach((table) => {{
      expandScenarios(table);
    }});
  </script>
</body>
</html>
"""


def _render_latest_redirect_html(
    bundle: dict[str, Any], *, latest_path: Path, outputs_root: Path
) -> str:
    bundle_href = _href_from(
        latest_path.parent,
        str(bundle.get("bundle_page_path") or ""),
        outputs_root=outputs_root,
    )
    target_href = bundle_href or "../bundles/"
    escaped_target = html.escape(target_href, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pylander Latest Report</title>
  <meta http-equiv="refresh" content="0; url={escaped_target}">
  <script>
    window.location.replace({json.dumps(target_href)});
  </script>
</head>
<body>
  <p>Redirecting to the latest report: <a href="{escaped_target}">{escaped_target}</a></p>
</body>
</html>
"""


def _benchmark_command(
    args: argparse.Namespace, *, intent_json_path: Path | None = None
) -> list[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "app.run_cached_benchmark",
        "--bot",
        args.bot,
        "--results-dir",
        args.results_dir,
        "--crash-detail-limit",
        str(max(0, int(args.crash_detail_limit))),
    ]
    if intent_json_path is not None:
        cmd.extend(["--intent-json", str(intent_json_path)])
    elif args.mode:
        cmd.extend(["--mode", args.mode])
    if str(getattr(args, "missing_baseline", "") or "").strip():
        cmd.extend(["--missing-baseline", str(args.missing_baseline)])
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
    if intent_json_path is None and args.baseline_ref:
        cmd.extend(["--baseline-ref", args.baseline_ref])
    if (
        intent_json_path is None
        and str(getattr(args, "goal_summary", "") or "").strip()
    ):
        cmd.extend(["--goal-summary", str(args.goal_summary)])
    if intent_json_path is None:
        for note in getattr(args, "context_note", []) or []:
            if str(note).strip():
                cmd.extend(["--context-note", str(note)])
    if args.no_reuse:
        cmd.append("--no-reuse")
    return cmd


def _bundle_payload(
    *,
    bundle_id: str,
    created_at_utc: str,
    benchmark_cmd: list[str],
    benchmark_exit_code: int,
    benchmark_wall_clock_s: float,
    candidate_json_path: Path,
    candidate_meta_path: Path,
    candidate_payload: dict[str, Any],
    candidate_cached: str | None,
    compare_path: Path | None,
    compare_payload: dict[str, Any] | None,
    baseline_json_path: Path | None,
    intent_path: Path | None,
    intent_payload: dict[str, Any] | None,
    analysis_path: Path | None,
    analysis_payload: dict[str, Any] | None,
    outputs_root: Path,
    viewer_assets: dict[str, str],
) -> dict[str, Any]:
    latest_page = "viewer/latest/index.html"
    bundle_page = f"viewer/bundles/{bundle_id}/index.html"
    bundle_json = f"viewer/bundles/{bundle_id}/bundle.json"
    return {
        "bundle_id": bundle_id,
        "created_at_utc": created_at_utc,
        "title": _bundle_title(
            candidate_json_path,
            compare=compare_path is not None and compare_payload is not None,
        ),
        "latest_page_path": latest_page,
        "bundle_page_path": bundle_page,
        "bundle_json_path": bundle_json,
        "viewer_assets": dict(viewer_assets),
        "timing": {
            "benchmark_wall_clock_s": float(benchmark_wall_clock_s),
            "bundle_render_wall_clock_s": None,
            "total_wall_clock_s": None,
        },
        "benchmark": {
            "command": benchmark_cmd,
            "exit_code": int(benchmark_exit_code),
            "records": [
                dict(item)
                for item in candidate_payload.get("records") or []
                if isinstance(item, dict)
            ],
            "candidate": {
                "cached": candidate_cached,
                "json_path": _rel_to_outputs(
                    candidate_json_path, outputs_root=outputs_root
                ),
                "meta_path": _rel_to_outputs(
                    candidate_meta_path, outputs_root=outputs_root
                ),
                "benchmark_wall_clock_s": _coerce_float(
                    candidate_payload.get("benchmark_wall_clock_s")
                ),
                "summary": dict(candidate_payload.get("summary") or {}),
                "schema": candidate_payload.get("schema"),
                "schema_version": candidate_payload.get("schema_version"),
                "trace_sample_period_s": candidate_payload.get("trace_sample_period_s"),
                "trace_detail": candidate_payload.get("trace_detail"),
                "trace_root_path": candidate_payload.get("trace_root_path"),
                "trace_root_rel": candidate_payload.get("trace_root_rel"),
            },
            "failures": _failure_rows(candidate_payload),
        },
        "compare": (
            {
                "json_path": _rel_to_outputs(compare_path, outputs_root=outputs_root),
                "baseline_json_path": _rel_to_outputs(
                    baseline_json_path, outputs_root=outputs_root
                ),
                "baseline_commit": str(compare_payload.get("baseline_commit") or ""),
                "candidate_commit": str(compare_payload.get("candidate_commit") or ""),
                **_compare_summary(compare_payload or {}),
            }
            if compare_path and compare_payload is not None
            else None
        ),
        "intent": (
            {
                "json_path": _rel_to_outputs(intent_path, outputs_root=outputs_root),
                **_intent_summary(intent_payload or {}),
            }
            if intent_path and intent_payload is not None
            else None
        ),
        "analysis": (
            {
                "json_path": _rel_to_outputs(analysis_path, outputs_root=outputs_root),
                **_analysis_summary(analysis_payload or {}),
            }
            if analysis_path and analysis_payload is not None
            else None
        ),
    }


def _write_bundle_files(
    bundle: dict[str, Any],
    *,
    outputs_root: Path,
) -> tuple[Path, Path, Path]:
    render_started = time.perf_counter()
    viewer_assets = dict(bundle.get("viewer_assets") or {}) or ensure_viewer_assets(
        outputs_root
    )
    bundle["viewer_assets"] = dict(viewer_assets)
    bundle_page_rel = Path(str(bundle["bundle_page_path"]))
    bundle_dir = (outputs_root / bundle_page_rel).parent
    bundle_dir.mkdir(parents=True, exist_ok=True)
    report = _build_bundle_report_model(bundle, outputs_root=outputs_root)
    detail_payloads: list[tuple[Path, str]] = []

    for run in report.get("runs") or []:
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
        for key in ("benchmark_wall_clock_s", "bundle_render_wall_clock_s")
    )
    bundle["timing"] = timing

    bundle_json_path = outputs_root / str(bundle["bundle_json_path"])
    bundle_json_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8"
    )

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
    latest_path.write_text(
        _render_latest_redirect_html(
            bundle, latest_path=latest_path, outputs_root=outputs_root
        ),
        encoding="utf-8",
    )
    return html_path, bundle_json_path, latest_path


def render_bundle(
    *,
    candidate_json_path: Path,
    candidate_meta_path: Path | None,
    compare_path: Path | None,
    baseline_json_path: Path | None,
    intent_path: Path | None,
    analysis_path: Path | None,
    benchmark_cmd: list[str] | None,
    benchmark_exit_code: int,
    benchmark_wall_clock_s: float | None,
    outputs_root: Path,
    created_at_utc: str | None = None,
    bundle_id: str | None = None,
    candidate_cached: str | None = None,
) -> BundleRenderResult:
    outputs_root = outputs_root.resolve()
    candidate_json_path = candidate_json_path.resolve()
    if not candidate_json_path.exists():
        raise SystemExit(f"Candidate benchmark JSON not found: {candidate_json_path}")

    resolved_meta_path = (
        candidate_meta_path.resolve()
        if candidate_meta_path is not None
        else _derive_meta_path(candidate_json_path)
    )
    resolved_compare_path = (
        compare_path.resolve()
        if compare_path is not None
        else discover_compare_path(candidate_json_path)
    )
    if resolved_compare_path is not None and not resolved_compare_path.exists():
        raise SystemExit(f"Compare JSON not found: {resolved_compare_path}")
    resolved_baseline_json_path = (
        baseline_json_path.resolve() if baseline_json_path is not None else None
    )
    if (
        resolved_baseline_json_path is not None
        and not resolved_baseline_json_path.exists()
    ):
        raise SystemExit(
            f"Baseline benchmark JSON not found: {resolved_baseline_json_path}"
        )
    resolved_intent_path = (
        intent_path.resolve()
        if intent_path is not None
        else (
            local_intent_path
            if (local_intent_path := intent_sidecar_path(candidate_json_path)).exists()
            else None
        )
    )
    if resolved_intent_path is not None and not resolved_intent_path.exists():
        raise SystemExit(f"Intent JSON not found: {resolved_intent_path}")
    resolved_analysis_path = (
        analysis_path.resolve()
        if analysis_path is not None
        else (
            local_analysis_path
            if (
                local_analysis_path := analysis_sidecar_path(candidate_json_path)
            ).exists()
            else None
        )
    )
    if resolved_analysis_path is not None and not resolved_analysis_path.exists():
        raise SystemExit(f"Analysis JSON not found: {resolved_analysis_path}")

    created_token = created_at_utc or datetime.now(timezone.utc).isoformat()
    local_bundle_id = _sanitize_token(
        bundle_id
        or f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{candidate_json_path.stem}"
    )
    viewer_assets = ensure_viewer_assets(outputs_root)
    candidate_payload = load_json(candidate_json_path)
    effective_benchmark_wall_clock_s = _coerce_float(benchmark_wall_clock_s)
    if effective_benchmark_wall_clock_s is None:
        effective_benchmark_wall_clock_s = (
            _coerce_float(candidate_payload.get("benchmark_wall_clock_s")) or 0.0
        )
    compare_payload = (
        load_json(resolved_compare_path) if resolved_compare_path is not None else None
    )
    if isinstance(compare_payload, dict):
        compare_candidate_json_path = _compare_tracepack_path(
            compare_payload.get("candidate_json_path"),
            outputs_root=outputs_root,
        )
        if (
            compare_candidate_json_path is not None
            and compare_candidate_json_path != candidate_json_path
        ):
            raise SystemExit(
                "Candidate benchmark JSON does not match compare JSON candidate: "
                f"{candidate_json_path} != {compare_candidate_json_path}"
            )
        if resolved_baseline_json_path is None:
            resolved_baseline_json_path = _compare_tracepack_path(
                compare_payload.get("baseline_json_path"),
                outputs_root=outputs_root,
            )
        compare_baseline_json_path = _compare_tracepack_path(
            compare_payload.get("baseline_json_path"),
            outputs_root=outputs_root,
        )
        if (
            compare_baseline_json_path is not None
            and resolved_baseline_json_path is not None
            and compare_baseline_json_path != resolved_baseline_json_path
        ):
            raise SystemExit(
                "Explicit baseline benchmark JSON does not match compare JSON baseline: "
                f"{resolved_baseline_json_path} != {compare_baseline_json_path}"
            )
        expected_candidate_ref = str(
            compare_payload.get("candidate_commit") or ""
        ).strip()
        actual_candidate_ref = _tracepack_ref_from_path(candidate_json_path)
        if (
            compare_candidate_json_path is None
            and expected_candidate_ref
            and actual_candidate_ref
            and expected_candidate_ref != actual_candidate_ref
        ):
            raise SystemExit(
                "Candidate benchmark JSON ref does not match compare JSON candidate ref: "
                f"{actual_candidate_ref} != {expected_candidate_ref}"
            )
        expected_baseline_ref = str(
            compare_payload.get("baseline_commit") or ""
        ).strip()
        actual_baseline_ref = _tracepack_ref_from_path(resolved_baseline_json_path)
        if (
            compare_baseline_json_path is None
            and resolved_baseline_json_path is not None
            and expected_baseline_ref
            and actual_baseline_ref
            and expected_baseline_ref != actual_baseline_ref
        ):
            raise SystemExit(
                "Baseline benchmark JSON ref does not match compare JSON baseline ref: "
                f"{actual_baseline_ref} != {expected_baseline_ref}"
            )
    if (
        resolved_baseline_json_path is not None
        and not resolved_baseline_json_path.exists()
    ):
        raise SystemExit(
            f"Baseline benchmark JSON not found: {resolved_baseline_json_path}"
        )
    intent_payload = (
        load_intent(resolved_intent_path) if resolved_intent_path is not None else None
    )
    analysis_payload = (
        load_json(resolved_analysis_path)
        if resolved_analysis_path is not None
        else None
    )
    bundle = _bundle_payload(
        bundle_id=local_bundle_id,
        created_at_utc=created_token,
        benchmark_cmd=list(benchmark_cmd or []),
        benchmark_exit_code=int(benchmark_exit_code),
        benchmark_wall_clock_s=effective_benchmark_wall_clock_s,
        candidate_json_path=candidate_json_path,
        candidate_meta_path=resolved_meta_path,
        candidate_payload=candidate_payload,
        candidate_cached=candidate_cached,
        compare_path=resolved_compare_path,
        compare_payload=compare_payload,
        baseline_json_path=resolved_baseline_json_path,
        intent_path=resolved_intent_path,
        intent_payload=intent_payload,
        analysis_path=resolved_analysis_path,
        analysis_payload=analysis_payload,
        outputs_root=outputs_root,
        viewer_assets=viewer_assets,
    )
    bundle_page_path, bundle_json_path, latest_page_path = _write_bundle_files(
        bundle,
        outputs_root=outputs_root,
    )
    return BundleRenderResult(
        bundle=bundle,
        candidate_json_path=candidate_json_path,
        candidate_meta_path=resolved_meta_path,
        compare_path=resolved_compare_path,
        intent_path=resolved_intent_path,
        analysis_path=resolved_analysis_path,
        bundle_page_path=bundle_page_path,
        bundle_json_path=bundle_json_path,
        latest_page_path=latest_page_path,
    )


def _resolve_server_context(
    *,
    outputs_root: Path,
    viewer_base_url: str | None,
    viewer_hostname: str | None,
    server_port: int,
    server_bind_host: str,
    ensure_server: bool,
) -> tuple[str, Path | None, str | None]:
    local_viewer_hostname = (
        str(viewer_hostname or "").strip() or discover_viewer_hostname()
    )
    server_state_path: Path | None = None
    server_status = "disabled"
    if ensure_server:
        server_status, server_state_path = ensure_outputs_server(
            outputs_root=outputs_root,
            bind_host=str(server_bind_host),
            port=int(server_port),
            viewer_hostname=local_viewer_hostname,
            repo_root=_REPO_ROOT,
        )
    base_url = _viewer_base_url(
        viewer_base_url=viewer_base_url,
        viewer_hostname=local_viewer_hostname,
        server_port=int(server_port),
        server_status=server_status,
    )
    return server_status, server_state_path, base_url


def _print_bundle_summary(
    *,
    result: BundleRenderResult,
    outputs_root: Path,
    server_status: str,
    server_state_path: Path | None,
    base_url: str | None,
    benchmark_wall_clock_s: float | None,
) -> None:
    latest_rel = (
        _rel_to_outputs(result.latest_page_path, outputs_root=outputs_root)
        or "viewer/latest/index.html"
    )
    bundle_rel = _rel_to_outputs(
        result.bundle_page_path, outputs_root=outputs_root
    ) or str(result.bundle.get("bundle_page_path") or "viewer/bundles/")
    bundle_json_rel = _rel_to_outputs(
        result.bundle_json_path, outputs_root=outputs_root
    ) or str(result.bundle.get("bundle_json_path") or "viewer/bundles/")
    latest_url = bundle_url(base_url, latest_rel)
    bundle_url_value = bundle_url(base_url, bundle_rel)

    timing = dict(result.bundle.get("timing") or {})
    benchmark_wall_clock_value = _coerce_float(benchmark_wall_clock_s)
    if benchmark_wall_clock_value is None:
        benchmark_wall_clock_value = _coerce_float(timing.get("benchmark_wall_clock_s"))
    if benchmark_wall_clock_value is None:
        benchmark_wall_clock_value = 0.0

    print("# bench_bundle")
    print(f"server_status={server_status}")
    if base_url is not None:
        print(f"viewer_base_url={base_url}")
    print(f"benchmark_wall_clock_s={benchmark_wall_clock_value:.3f}")
    if timing.get("bundle_render_wall_clock_s") is not None:
        print(
            f"bundle_render_wall_clock_s={float(timing['bundle_render_wall_clock_s']):.3f}"
        )
    if timing.get("total_wall_clock_s") is not None:
        print(f"total_wall_clock_s={float(timing['total_wall_clock_s']):.3f}")
    if server_state_path is not None:
        print(f"server_state={server_state_path}")
    print(f"candidate_json={result.candidate_json_path}")
    print(f"candidate_meta={result.candidate_meta_path}")
    if result.compare_path is not None:
        print(f"compare_json={result.compare_path}")
    if result.intent_path is not None:
        print(f"intent_json={result.intent_path}")
    if result.analysis_path is not None:
        print(f"analysis_json={result.analysis_path}")
    print(f"bundle_page={result.bundle_page_path}")
    print(f"bundle_json={result.bundle_json_path}")
    print(f"latest_page={result.latest_page_path}")
    print(f"latest_rel={_root_path(latest_rel) or '/viewer/latest/index.html'}")
    print(f"bundle_rel={_root_path(bundle_rel) or '/viewer/bundles/'}")
    print(f"bundle_json_rel={_root_path(bundle_json_rel) or '/viewer/bundles/'}")
    if bundle_url_value:
        print(f"bundle_url={bundle_url_value}")
    if latest_url:
        print(f"latest_url={latest_url}")


def build_bundle_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run the full benchmark workflow and write a static HTML bundle"
    )
    ap.add_argument(
        "--mode", choices=("smoke", "quick", "full", "focused"), default=None
    )
    ap.add_argument("--seed-spec", default=None)
    ap.add_argument("--selectors", nargs="*", default=[])
    ap.add_argument("--exclude-levels", nargs="*", default=[])
    ap.add_argument("--observe-only-levels", nargs="*", default=[])
    ap.add_argument("--bot", default="pdg")
    ap.add_argument("--bot-config", default=None)
    ap.add_argument(
        "--bot-profile", action=argparse.BooleanOptionalAction, default=True
    )
    ap.add_argument("--bot-profile-interval-s", type=float, default=None)
    ap.add_argument(
        "--bot-profile-logs", action=argparse.BooleanOptionalAction, default=False
    )
    ap.add_argument("--baseline-ref", default="auto")
    ap.add_argument(
        "--missing-baseline",
        choices=("skip", "seed", "error"),
        default=None,
    )
    ap.add_argument("--intent-json", default=None)
    ap.add_argument("--goal-summary", default=None)
    ap.add_argument("--context-note", action="append", default=[])
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument("--no-reuse", action="store_true")
    ap.add_argument("--crash-detail-limit", type=int, default=8)
    ap.add_argument("--viewer-base-url", default=None)
    ap.add_argument("--viewer-hostname", default=None)
    ap.add_argument("--server-port", type=int, default=8765)
    ap.add_argument("--server-bind-host", default="0.0.0.0")
    ap.add_argument(
        "--ensure-server", action=argparse.BooleanOptionalAction, default=True
    )
    return ap


def build_report_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Render a static HTML bundle from existing benchmark artifacts"
    )
    ap.add_argument("--candidate-json", required=True)
    ap.add_argument("--candidate-meta", default=None)
    ap.add_argument("--compare-json", default=None)
    ap.add_argument("--baseline-json", default=None)
    ap.add_argument("--intent-json", default=None)
    ap.add_argument("--analysis-json", default=None)
    ap.add_argument("--benchmark-command", default=None)
    ap.add_argument("--benchmark-exit-code", type=int, default=0)
    ap.add_argument("--benchmark-wall-clock-s", type=float, default=None)
    ap.add_argument("--viewer-base-url", default=None)
    ap.add_argument("--viewer-hostname", default=None)
    ap.add_argument("--server-port", type=int, default=8765)
    ap.add_argument("--server-bind-host", default="0.0.0.0")
    ap.add_argument(
        "--ensure-server", action=argparse.BooleanOptionalAction, default=True
    )
    return ap


def _repo_path(path_value: str | None) -> Path | None:
    token = str(path_value or "").strip()
    if not token:
        return None
    path = Path(token).expanduser()
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _prepare_bundle_intent(
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any], Path | None]:
    intent_path = _repo_path(args.intent_json)
    if intent_path is not None:
        if not intent_path.exists():
            raise SystemExit(f"Intent JSON not found: {intent_path}")
        return intent_path, load_intent(intent_path), None

    if not args.mode:
        raise SystemExit("--mode is required unless --intent-json is provided")

    try:
        pack = build_selectors(
            mode=str(args.mode),
            seed_spec=args.seed_spec,
            focused_selectors=list(args.selectors or []),
            exclude_levels=list(args.exclude_levels or []),
            observe_only_levels=list(args.observe_only_levels or []),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    results_root = (_REPO_ROOT / str(args.results_dir)).resolve()
    inspect_payload = build_inspect_payload(
        mode=str(args.mode),
        seed_spec=args.seed_spec,
        selectors=list(args.selectors or []),
        exclude_levels=list(args.exclude_levels or []),
        observe_only_levels=list(args.observe_only_levels or []),
        bot=str(args.bot),
        trace_detail="report",
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=args.bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
        baseline_ref=args.baseline_ref,
        results_root=results_root,
    )
    preview = dict(inspect_payload.get("pack_preview") or {})
    candidate_json = _repo_path(str(preview.get("candidate_json") or ""))
    if candidate_json is None:
        raise SystemExit("Unable to derive candidate benchmark path for bundle intent.")
    local_inspect_path = _repo_path(
        str(preview.get("candidate_inspect") or inspect_sidecar_path(candidate_json))
    )
    if local_inspect_path is not None:
        write_json(local_inspect_path, inspect_payload)

    intent_payload, local_intent_path = build_auto_intent(
        inspect_payload=inspect_payload,
        pack=pack,
        mode=str(args.mode),
        seed_spec=args.seed_spec,
        bot=str(args.bot),
        trace_detail="report",
        bot_config_path=args.bot_config,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=args.bot_profile_interval_s,
        bot_profile_log_lines=bool(args.bot_profile_logs),
        baseline_ref=args.baseline_ref,
        missing_baseline_policy=args.missing_baseline,
        results_root=results_root,
        goal_summary=args.goal_summary,
        context_notes=list(args.context_note or []),
    )
    write_json(local_intent_path, intent_payload)
    return local_intent_path, intent_payload, local_inspect_path


def report_main(argv: Sequence[str] | None = None) -> None:
    args = build_report_parser().parse_args(list(argv) if argv is not None else None)

    outputs_root = (_REPO_ROOT / "outputs").resolve()
    server_status, server_state_path, base_url = _resolve_server_context(
        outputs_root=outputs_root,
        viewer_base_url=args.viewer_base_url,
        viewer_hostname=args.viewer_hostname,
        server_port=int(args.server_port),
        server_bind_host=str(args.server_bind_host),
        ensure_server=bool(args.ensure_server),
    )
    candidate_json_path = _output_path(args.candidate_json, repo_root=_REPO_ROOT)
    if candidate_json_path is None:
        raise SystemExit("--candidate-json is required")
    candidate_meta_path = _output_path(args.candidate_meta, repo_root=_REPO_ROOT)
    compare_path = _output_path(args.compare_json, repo_root=_REPO_ROOT)
    baseline_json_path = _output_path(args.baseline_json, repo_root=_REPO_ROOT)
    intent_path = _output_path(args.intent_json, repo_root=_REPO_ROOT)
    analysis_path = _output_path(args.analysis_json, repo_root=_REPO_ROOT)
    benchmark_cmd = (
        shlex.split(str(args.benchmark_command))
        if str(args.benchmark_command or "").strip()
        else []
    )
    result = render_bundle(
        candidate_json_path=candidate_json_path,
        candidate_meta_path=candidate_meta_path,
        compare_path=compare_path,
        baseline_json_path=baseline_json_path,
        intent_path=intent_path,
        analysis_path=analysis_path,
        benchmark_cmd=benchmark_cmd,
        benchmark_exit_code=int(args.benchmark_exit_code),
        benchmark_wall_clock_s=_coerce_float(args.benchmark_wall_clock_s),
        outputs_root=outputs_root,
    )
    _print_bundle_summary(
        result=result,
        outputs_root=outputs_root,
        server_status=server_status,
        server_state_path=server_state_path,
        base_url=base_url,
        benchmark_wall_clock_s=_coerce_float(args.benchmark_wall_clock_s),
    )
    raise SystemExit(int(args.benchmark_exit_code))


def main(argv: Sequence[str] | None = None) -> None:
    args = build_bundle_parser().parse_args(list(argv) if argv is not None else None)

    outputs_root = (_REPO_ROOT / "outputs").resolve()
    server_status, server_state_path, base_url = _resolve_server_context(
        outputs_root=outputs_root,
        viewer_base_url=args.viewer_base_url,
        viewer_hostname=args.viewer_hostname,
        server_port=int(args.server_port),
        server_bind_host=str(args.server_bind_host),
        ensure_server=bool(args.ensure_server),
    )
    intent_path, intent_payload, _inspect_path = _prepare_bundle_intent(args)
    benchmark_cmd = _benchmark_command(args, intent_json_path=intent_path)
    benchmark_started = time.perf_counter()
    benchmark_exit_code, benchmark_output = run_command(benchmark_cmd, cwd=_REPO_ROOT)
    benchmark_wall_clock_s = time.perf_counter() - benchmark_started

    intent_section = _parse_section(benchmark_output, "intent")
    resolved_intent_path = _output_path(
        intent_section.get("json"), repo_root=_REPO_ROOT
    )
    if resolved_intent_path is not None:
        intent_path = resolved_intent_path
        intent_payload = load_intent(intent_path)

    candidate_section = _parse_section(benchmark_output, "candidate")
    candidate_json_path = _output_path(
        candidate_section.get("json"), repo_root=_REPO_ROOT
    )
    if candidate_json_path is None or not candidate_json_path.exists():
        raise SystemExit(
            "Unable to resolve candidate benchmark JSON from run_cached_benchmark output.\n"
            f"exit_code={benchmark_exit_code}\n{benchmark_output}"
        )
    candidate_meta_path = _output_path(
        candidate_section.get("meta"), repo_root=_REPO_ROOT
    )
    baseline_section = _parse_section(benchmark_output, "baseline")
    baseline_json_path = _output_path(
        baseline_section.get("json"), repo_root=_REPO_ROOT
    )
    compare_section = _parse_section(benchmark_output, "compare_report")
    compare_path = _output_path(compare_section.get("json"), repo_root=_REPO_ROOT)
    candidate_payload = load_json(candidate_json_path)
    compare_payload = load_json(compare_path) if compare_path is not None else None
    analysis_path = analysis_sidecar_path(candidate_json_path)
    analysis_payload = build_analysis_payload(
        candidate_payload=candidate_payload,
        compare_payload=compare_payload,
        intent_payload=intent_payload,
        candidate_json_path=candidate_json_path,
    )
    write_json(analysis_path, analysis_payload)
    result = render_bundle(
        candidate_json_path=candidate_json_path,
        candidate_meta_path=candidate_meta_path,
        compare_path=compare_path,
        baseline_json_path=baseline_json_path,
        intent_path=intent_path,
        analysis_path=analysis_path,
        benchmark_cmd=benchmark_cmd,
        benchmark_exit_code=benchmark_exit_code,
        benchmark_wall_clock_s=benchmark_wall_clock_s,
        outputs_root=outputs_root,
        candidate_cached=candidate_section.get("cached"),
    )
    _print_bundle_summary(
        result=result,
        outputs_root=outputs_root,
        server_status=server_status,
        server_state_path=server_state_path,
        base_url=base_url,
        benchmark_wall_clock_s=benchmark_wall_clock_s,
    )
    raise SystemExit(benchmark_exit_code)


__all__ = [
    "BundleRenderResult",
    "build_bundle_parser",
    "build_report_parser",
    "load_json",
    "main",
    "render_bundle",
    "report_main",
    "run_command",
]


if __name__ == "__main__":
    main()
