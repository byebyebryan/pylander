from __future__ import annotations

import argparse
import html
import json
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
from app.benchmark_cache import tracepack_meta_path, write_json
from app.output_viewer import (
    bundle_url,
    discover_viewer_hostname,
    ensure_outputs_server,
    normalize_base_url,
)
from app.selector_pack import build_selectors

from core.selector_codec import render_record_selector
from levels.registry import (
    list_public_levels,
    resolve_selector_binding,
    selector_children,
    selector_path_looks_like_seed,
)
from utils.tracebundle import (
    artifact_path as _artifact_path,
    href_from_outputs as _href_from,
    output_path as _output_path,
    rel_to_outputs as _rel_to_outputs,
    sanitize_token as _sanitize_token,
)
from utils.traceviewer import (
    PLOTLY_CDN_URL,
    ensure_viewer_assets,
    render_trace_detail_html,
)

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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _format_timestamp(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return "-"
    try:
        dt = datetime.fromisoformat(token)
    except ValueError:
        return token
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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


def _summary_card_sections(
    bundle: dict[str, Any],
) -> list[tuple[str, list[tuple[str, str]]]]:
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    summary = dict(candidate.get("summary") or {})
    timing = dict(bundle.get("timing") or {})
    runs = int(summary.get("runs", 0) or 0)
    successes = int(summary.get("successes", 0) or 0)
    failures = max(0, runs - successes)
    cached_value = str(candidate.get("cached") or "").strip()
    cached_label = (
        "-" if not cached_value else ("yes" if cached_value.lower() == "true" else "no")
    )
    wall_breakdown = (
        " / ".join(
            part
            for part in (
                f"bench {_format_seconds(timing.get('benchmark_wall_clock_s'))}"
                if timing.get("benchmark_wall_clock_s") is not None
                else "",
                f"render {_format_seconds(timing.get('bundle_render_wall_clock_s'))}"
                if timing.get("bundle_render_wall_clock_s") is not None
                else "",
            )
            if part
        )
        or "-"
    )
    return [
        (
            "Bench",
            [
                ("Bench Id", str(bundle.get("bundle_id") or "-")),
                ("Time", _format_timestamp(bundle.get("created_at_utc"))),
                ("Cached", cached_label),
            ],
        ),
        (
            "Wall Clock",
            [
                ("Wall Clock Total", _format_seconds(timing.get("total_wall_clock_s"))),
                ("Wall Clock Breakdown", wall_breakdown),
            ],
        ),
        (
            "Outcome",
            [
                ("Runs", str(runs)),
                ("Success", str(successes)),
                ("Success Rate", _format_percent(summary.get("success_rate"))),
                ("Failure", str(failures)),
            ],
        ),
        (
            "Efficiency",
            [
                (
                    "Fuel Mean",
                    _format_float(
                        _summary_metric(summary, "fuel_consumed", scope="all").get(
                            "mean"
                        )
                    ),
                ),
                (
                    "Fuel Mean Success",
                    _format_float(
                        _summary_metric(summary, "fuel_consumed", scope="success").get(
                            "mean"
                        )
                    ),
                ),
                (
                    "Time Mean",
                    _format_float(
                        _summary_metric(summary, "time", scope="all").get("mean")
                    ),
                ),
                (
                    "Time Mean Success",
                    _format_float(
                        _summary_metric(summary, "time", scope="success").get("mean")
                    ),
                ),
            ],
        ),
        (
            "Bot Tick",
            [
                (
                    "Bot Tick Mean",
                    _format_float(
                        _summary_metric(
                            summary, "bot_profile_total_ms_per_tick", scope="all"
                        ).get("mean")
                    ),
                ),
                (
                    "Bot Tick P90",
                    _format_float(
                        _summary_metric(
                            summary, "bot_profile_total_ms_per_tick_p90", scope="all"
                        ).get("mean")
                    ),
                ),
                (
                    "Bot Tick P99",
                    _format_float(
                        _summary_metric(
                            summary, "bot_profile_total_ms_per_tick_p99", scope="all"
                        ).get("mean")
                    ),
                ),
            ],
        ),
    ]


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


def _record_detail_rel_path(bundle_id: str, record: dict[str, Any]) -> str:
    run_key = str(record.get("run_key") or "").strip()
    if not run_key:
        run_key = render_record_selector(record)
    return f"viewer/bundles/{bundle_id}/runs/{_sanitize_token(run_key)}.html"


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


def _scenario_summary_data(
    summary_row: dict[str, Any], runs: list[dict[str, Any]]
) -> dict[str, Any]:
    eff_success = dict(summary_row.get("efficiency_success") or {})
    fuel_mean = dict(eff_success.get("fuel_consumed") or {}).get("mean")
    time_mean = dict(eff_success.get("time") or {}).get("mean")
    total_ms_mean = dict(eff_success.get("bot_profile_total_ms_per_tick") or {}).get(
        "mean"
    )
    if fuel_mean is None:
        fuel_mean = _mean(
            [
                float(run["record"].get("fuel_consumed"))
                for run in runs
                if run["record"].get("fuel_consumed") is not None
                and bool(run["record"].get("success", False))
            ]
        )
    if time_mean is None:
        time_mean = _mean(
            [
                float(run["record"].get("time"))
                for run in runs
                if run["record"].get("time") is not None
                and bool(run["record"].get("success", False))
            ]
        )
    if total_ms_mean is None:
        total_ms_mean = _mean(
            [
                float(run["record"].get("bot_profile_total_ms_per_tick"))
                for run in runs
                if run["record"].get("bot_profile_total_ms_per_tick") is not None
                and bool(run["record"].get("success", False))
            ]
        )

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
        "fuel_mean": fuel_mean,
        "time_mean": time_mean,
        "total_ms_mean": total_ms_mean,
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
    benchmark = dict(bundle.get("benchmark") or {})
    candidate = dict(benchmark.get("candidate") or {})
    summary = dict(candidate.get("summary") or {})
    bundle_id = str(bundle.get("bundle_id") or "bundle")

    records = [
        dict(item) for item in benchmark.get("records") or [] if isinstance(item, dict)
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
        detail_rel = _record_detail_rel_path(bundle_id, record)
        trace_assets = _load_trace_asset_paths(record, outputs_root=outputs_root)
        run_info = {
            "selector": run_selector,
            "scenario_selector": scenario_selector,
            "record": record,
            "detail_rel": detail_rel,
            "run_key": str(record.get("run_key") or run_selector),
            "run_instance_id": int(record.get("run_instance_id", 1) or 1),
            "duplicate_count": duplicate_counts.get(run_selector, 1),
            **trace_assets,
        }
        runs_by_scenario.setdefault(scenario_selector, []).append(run_info)
        runs.append(run_info)
        if not bool(record.get("success", False)):
            failures.append(run_info)

    scenario_trees_by_level = _build_scenario_trees(
        runs_by_scenario=runs_by_scenario, summary=summary
    )

    return {
        "scenario_trees_by_level": scenario_trees_by_level,
        "failures": sorted(
            failures,
            key=lambda item: _selector_sort_key(str(item.get("selector") or "")),
        ),
        "runs": runs,
    }


def _render_metric_card_grid(cards: list[tuple[str, str]]) -> str:
    return "".join(
        '<div class="card">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div>'
        "</div>"
        for label, value in cards
    )


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


def _render_context_section(intent: dict[str, Any]) -> str:
    if not intent:
        return ""
    rows = [
        ["Goal", html.escape(str(intent.get("goal_summary") or "-"))],
        ["Request Source", html.escape(str(intent.get("request_source") or "-"))],
        [
            "Touched Areas",
            _render_inline_list(list(intent.get("touched_areas") or []), code=True),
        ],
        [
            "Changed Files",
            _render_inline_list(list(intent.get("changed_files") or [])[:10], code=True),
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


def _render_baseline_section(intent: dict[str, Any]) -> str:
    if not intent:
        return ""
    skipped_commits = list(intent.get("baseline_skipped_commits") or [])
    rows = _render_table(
        ["Field", "Value"],
        [
            ["Strategy", html.escape(str(intent.get("baseline_strategy") or "-"))],
            [
                "Requested Ref",
                html.escape(str(intent.get("baseline_requested_ref") or "-")),
            ],
            [
                "Missing Baseline Policy",
                html.escape(str(intent.get("baseline_missing_policy") or "-")),
            ],
            [
                "Resolved Ref",
                html.escape(str(intent.get("baseline_resolved_ref") or "-")),
            ],
        ],
    )
    sections = [
        "<section>",
        "<h2>Baseline</h2>",
        rows,
    ]
    if skipped_commits:
        sections.append("<h3>Skipped Commits</h3>")
        sections.append(
            _render_table(
                ["Commit", "Reason", "Subject"],
                [
                    [
                        f"<code>{html.escape(str(item.get('commit') or '-'))}</code>",
                        html.escape(str(item.get("skip_reason") or "-")),
                        html.escape(str(item.get("subject") or "-")),
                    ]
                    for item in skipped_commits
                    if isinstance(item, dict)
                ],
            )
        )
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

    def _render_preview_cell(
        selector: str, representative_run: dict[str, Any] | None
    ) -> str:
        if representative_run is None:
            return '<span class="muted">expand</span>'
        preview_href = _href_from(
            bundle_dir,
            str(representative_run.get("preview_path_rel") or ""),
            outputs_root=outputs_root,
        )
        detail_href = _href_from(
            bundle_dir,
            str(representative_run.get("detail_rel") or ""),
            outputs_root=outputs_root,
        )
        if not preview_href or not detail_href:
            return '<span class="muted">expand</span>'
        return (
            f'<a class="table-preview" href="{html.escape(detail_href)}">'
            f'<img src="{html.escape(preview_href)}" alt="{html.escape(selector)}">'
            "</a>"
        )

    def _render_tree_rows(
        node: dict[str, Any], *, parent_group_id: str | None
    ) -> list[str]:
        selector = str(node.get("selector") or "")
        group_id = _sanitize_token(selector)
        depth = int(node.get("depth", 0) or 0)
        summary_data = dict(node.get("summary") or {})
        hidden_attr = " hidden" if parent_group_id else ""
        parent_attr = (
            f' data-parent="{html.escape(parent_group_id)}"' if parent_group_id else ""
        )
        preview_cell = _render_preview_cell(selector, node.get("representative_run"))
        rows = [
            (
                '<tr class="scenario-row"'
                f"{hidden_attr}{parent_attr}"
                f' data-group="{html.escape(group_id)}" aria-expanded="false" tabindex="0">'
                f'<td class="tree-label" style="--depth: {depth};"><span class="expander">+</span>{html.escape(selector)}</td>'
                f"<td>{html.escape(str(int(summary_data.get('successes', 0) or 0)) + '/' + str(int(summary_data.get('runs', 0) or 0)))}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('fuel_mean')))}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('time_mean')))}</td>"
                f"<td>{html.escape(_format_float(summary_data.get('total_ms_mean')))}</td>"
                f"<td>{preview_cell}</td>"
                "</tr>"
            )
        ]

        children = list(node.get("children") or [])
        if children:
            for child in children:
                rows.extend(_render_tree_rows(child, parent_group_id=group_id))
            return rows

        for run in node.get("runs") or []:
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
            metric_text = f"offset={_format_float(record.get('landing_offset'), 3)}"
            seed_label = (
                f"seed {record.get('seed') if record.get('seed') is not None else '-'}"
            )
            if int(run.get("duplicate_count", 1) or 1) > 1:
                seed_label = f"{seed_label} #{int(run.get('run_instance_id', 1) or 1)}"
            rows.append(
                '<tr class="seed-row" hidden'
                f' data-parent="{html.escape(group_id)}">'
                f'<td class="tree-label seed-label" style="--depth: {depth + 1};">{html.escape(str(seed_label))}</td>'
                f"<td>{html.escape(str(record.get('state') or ''))}</td>"
                f"<td>{html.escape(_format_float(record.get('fuel_consumed'), 3))}</td>"
                f"<td>{html.escape(_format_float(record.get('time'), 3))}</td>"
                f"<td>{html.escape(metric_text)}</td>"
                f"<td>{preview_cell}</td>"
                "</tr>"
            )
        return rows

    sections: list[str] = []
    for level_name in sorted(report["scenario_trees_by_level"], key=_selector_sort_key):
        table_counter += 1
        table_id = f"scenario-table-{table_counter}"
        row_blocks: list[str] = []
        for node in report["scenario_trees_by_level"][level_name]:
            row_blocks.extend(_render_tree_rows(node, parent_group_id=None))
        sections.append(
            "<section>"
            f"<h2>{html.escape(level_name.title())}</h2>"
            f'<div class="table-controls"><button type="button" class="table-button" data-action="expand" data-target="{html.escape(table_id)}">Expand All</button><button type="button" class="table-button" data-action="collapse" data-target="{html.escape(table_id)}">Collapse All</button></div>'
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
    record = dict(run.get("record") or {})
    selector = str(run.get("selector") or "unknown")
    trace_payload = _load_trace_payload(run, outputs_root=outputs_root)
    detail_dir = (outputs_root / str(run["detail_rel"])).parent
    index_href = (
        _href_from(
            detail_dir,
            str(bundle.get("bundle_page_path") or ""),
            outputs_root=outputs_root,
        )
        or "../index.html"
    )
    latest_href = _href_from(
        detail_dir, str(bundle.get("latest_page_path") or ""), outputs_root=outputs_root
    )
    candidate_href = _href_from(
        detail_dir, candidate.get("json_path"), outputs_root=outputs_root
    )
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
        top_links=[
            ("bundle report", index_href),
            ("latest page", latest_href),
        ],
        raw_links=[
            ("candidate json", candidate_href),
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
    summary_sections_html = "".join(
        '<div class="card-group">'
        f"<h2>{html.escape(title)}</h2>"
        f'<div class="cards">{_render_metric_card_grid(cards)}</div>'
        "</div>"
        for title, cards in _summary_card_sections(bundle)
    )

    raw_links: list[str] = []
    for label, path_rel in (
        ("candidate json", candidate.get("json_path")),
        ("candidate meta", candidate.get("meta_path")),
        ("compare report", compare.get("json_path")),
        ("intent json", intent.get("json_path")),
        ("analysis json", analysis.get("json_path")),
        ("bundle json", bundle.get("bundle_json_path")),
    ):
        href = _href_from(bundle_dir, path_rel, outputs_root=outputs_root)
        if href is None:
            continue
        raw_links.append(f'<a href="{html.escape(href)}">{html.escape(label)}</a>')

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
            f'<p class="banner {"bad" if compare.get("notable_regression") else "ok"}">'
            f"notable_regression={html.escape(str(compare.get('notable_regression')))}</p>"
            "<h3>New Global Crashes</h3>"
            f"{crash_rows}"
            "<h3>Worst Scenarios</h3>"
            f"{worst_rows}"
            "</section>"
        )

    benchmark_cmd = html.escape(
        " ".join(str(item) for item in benchmark.get("command") or [])
    )
    latest_href = _href_from(
        bundle_dir, bundle.get("latest_page_path"), outputs_root=outputs_root
    )
    intent_html = _render_context_section(intent) + _render_baseline_section(intent)
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
    .card-group + .card-group {{
      margin-top: 18px;
    }}
    .card-group h2 {{
      margin: 0 0 10px;
      font-size: 1rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin: 0;
    }}
    .card, section, .plot-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 24px var(--shadow);
    }}
    .card {{
      padding: 14px;
      min-width: 0;
    }}
    .label {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
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
    .links {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .table-wrap {{ overflow-x: auto; }}
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
      background: rgba(14, 107, 96, 0.04);
    }}
    .failure-row {{
      background: rgba(142, 59, 46, 0.05);
    }}
    .scenario-row:hover {{
      background: rgba(14, 107, 96, 0.08);
    }}
    .scenario-row td:first-child {{
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
      background: rgba(255, 250, 240, 0.55);
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
      <h1>{html.escape(str(bundle.get("title") or "Pylander Bench Bundle"))}</h1>
      {summary_sections_html}
      <p class="links">{" | ".join(raw_links)}</p>
      <p class="links">{f'<a href="{html.escape(latest_href)}">latest page</a>' if latest_href else ""}</p>
      <details>
        <summary>Show commands</summary>
        <p><code>{benchmark_cmd}</code></p>
      </details>
    </header>

    {compare_html}
    {intent_html}
    {analysis_html}

    <section>
      <h2>Failures</h2>
      {failure_sections_html}
    </section>

    {scenario_sections_html}
  </main>
  <script>
    const rowsForTable = (table) => Array.from(table.querySelectorAll("tr.scenario-row, tr.seed-row"));
    const childRows = (table, group) => Array.from(table.querySelectorAll(`tr[data-parent="${{group}}"]`));

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
        if (button.dataset.action === "expand") {{
          expandAll(table);
        }} else {{
          collapseAll(table);
        }}
      }});
    }});
  </script>
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
    if intent_json_path is None and str(getattr(args, "goal_summary", "") or "").strip():
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
        "title": f"Pylander Bench Bundle {bundle_id}",
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
        _render_bundle_html(
            bundle, bundle_dir=latest_path.parent, outputs_root=outputs_root
        ),
        encoding="utf-8",
    )
    return html_path, bundle_json_path, latest_path


def render_bundle(
    *,
    candidate_json_path: Path,
    candidate_meta_path: Path | None,
    compare_path: Path | None,
    intent_path: Path | None,
    analysis_path: Path | None,
    benchmark_cmd: list[str] | None,
    benchmark_exit_code: int,
    benchmark_wall_clock_s: float,
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
            if (local_analysis_path := analysis_sidecar_path(candidate_json_path)).exists()
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
    compare_payload = (
        load_json(resolved_compare_path)
        if resolved_compare_path is not None
        else None
    )
    intent_payload = (
        load_intent(resolved_intent_path)
        if resolved_intent_path is not None
        else None
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
        benchmark_wall_clock_s=float(benchmark_wall_clock_s),
        candidate_json_path=candidate_json_path,
        candidate_meta_path=resolved_meta_path,
        candidate_payload=candidate_payload,
        candidate_cached=candidate_cached,
        compare_path=resolved_compare_path,
        compare_payload=compare_payload,
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
    benchmark_wall_clock_s: float,
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

    print("# bench_bundle")
    print(f"server_status={server_status}")
    if base_url is not None:
        print(f"viewer_base_url={base_url}")
    print(f"benchmark_wall_clock_s={benchmark_wall_clock_s:.3f}")
    timing = dict(result.bundle.get("timing") or {})
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
    ap.add_argument("--mode", choices=("smoke", "quick", "full", "focused"), default=None)
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
    ap.add_argument("--intent-json", default=None)
    ap.add_argument("--analysis-json", default=None)
    ap.add_argument("--benchmark-command", default=None)
    ap.add_argument("--benchmark-exit-code", type=int, default=0)
    ap.add_argument("--benchmark-wall-clock-s", type=float, default=0.0)
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
        intent_path=intent_path,
        analysis_path=analysis_path,
        benchmark_cmd=benchmark_cmd,
        benchmark_exit_code=int(args.benchmark_exit_code),
        benchmark_wall_clock_s=float(args.benchmark_wall_clock_s),
        outputs_root=outputs_root,
    )
    _print_bundle_summary(
        result=result,
        outputs_root=outputs_root,
        server_status=server_status,
        server_state_path=server_state_path,
        base_url=base_url,
        benchmark_wall_clock_s=float(args.benchmark_wall_clock_s),
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
    resolved_intent_path = _output_path(intent_section.get("json"), repo_root=_REPO_ROOT)
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
