from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.selector_codec import render_record_selector, render_selector
from utils.botmetrics import bot_metric_key
from utils.tracebundle import (
    href_from as _href_from,
    output_path as _output_path,
    rel_to_outputs as _rel_to_outputs,
    sanitize_token as _sanitize_token,
)
from utils.traceviewer import PLOTLY_FILENAME, ensure_viewer_assets, render_trace_detail_html

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def split_csv(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        for token in str(item).split(","):
            t = token.strip()
            if t:
                out.append(t)
    return out


def selector_from_record(record: dict[str, Any]) -> str:
    return render_record_selector(record)


def selector_from_triplet(
    level: str,
    scenario: str,
    seed: int | str | None,
    *,
    eval_goal: str = "landing",
) -> str:
    return render_selector(
        level_name=str(level or "").strip() or "unknown",
        scenario_name=str(scenario or "").strip() or None,
        goal=str(eval_goal or "landing").strip().lower() or "landing",
        seed_token="0" if seed is None else str(seed),
    )


def _abs_float(value: Any) -> float:
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def build_cases_from_records(
    records: list[dict[str, Any]],
    *,
    top_n: int,
    bot: str,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    terminal_dx_key = bot_metric_key(
        bot, "terminal_entry_projected_dx", fallback="unknown"
    )

    for rec in records:
        if str(rec.get("state") or "") == "crashed":
            cases.append(
                {
                    "selector": selector_from_record(rec),
                    "severity": "critical",
                    "reason": "crash",
                    "evidence": {
                        "state": rec.get("state"),
                        "failure_mode": rec.get("failure_mode"),
                    },
                }
            )

    ranked = sorted(
        records,
        key=lambda r: (
            _abs_float(r.get("boost_cutoff_projected_dx")),
            _abs_float(r.get(terminal_dx_key)),
            _abs_float(r.get("fuel_consumed")),
        ),
        reverse=True,
    )
    for rec in ranked:
        boost_dx = _abs_float(rec.get("boost_cutoff_projected_dx"))
        terminal_dx = _abs_float(rec.get(terminal_dx_key))
        fuel = _abs_float(rec.get("fuel_consumed"))
        if boost_dx <= 0.0 and terminal_dx <= 0.0 and fuel <= 0.0:
            continue
        reason = "high_boost_dx" if boost_dx >= terminal_dx else "high_terminal_dx"
        if boost_dx < 1.0 and terminal_dx < 1.0:
            reason = "high_fuel"
        severity = "high" if boost_dx >= 100.0 or terminal_dx >= 50.0 else "medium"
        cases.append(
            {
                "selector": selector_from_record(rec),
                "severity": severity,
                "reason": reason,
                "evidence": {
                    "boost_cutoff_projected_dx": rec.get("boost_cutoff_projected_dx"),
                    "bot_terminal_entry_projected_dx_field": terminal_dx_key,
                    "bot_terminal_entry_projected_dx": rec.get(terminal_dx_key),
                    "fuel_consumed": rec.get("fuel_consumed"),
                },
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        selector = str(case.get("selector") or "").strip()
        if not selector or selector in seen:
            continue
        seen.add(selector)
        deduped.append(case)
        if len(deduped) >= max(1, int(top_n)):
            break
    return deduped


def build_cases_from_compare(
    compare: dict[str, Any], *, top_n: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    global_block = dict(compare.get("global") or {})
    crash_block = dict(global_block.get("crash") or {})
    for item in crash_block.get("new_crashes") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "selector": selector_from_triplet(
                    str(item.get("level") or "unknown"),
                    str(item.get("scenario") or ""),
                    item.get("seed"),
                    eval_goal=str(item.get("eval_goal") or "landing"),
                ),
                "severity": "critical",
                "reason": "new_global_crash",
                "evidence": {
                    "candidate_failure_mode": item.get("candidate_failure_mode"),
                    "baseline_state": item.get("baseline_state"),
                    "candidate_state": item.get("candidate_state"),
                },
            }
        )

    worst = global_block.get("worst_scenarios") or []
    for row in worst:
        if not isinstance(row, dict):
            continue
        scenario = str(row.get("scenario") or "").strip()
        if not scenario:
            continue
        parts = scenario.split(":", 1)
        if len(parts) != 2:
            continue
        level_name, scenario_name = parts
        out.append(
            {
                "selector": selector_from_triplet(level_name, scenario_name, 0),
                "severity": "high",
                "reason": "worst_scenario_regression",
                "evidence": {
                    "delta_success_rate": row.get("delta_success_rate"),
                    "delta_fuel_mean": row.get("delta_fuel_mean"),
                },
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in out:
        selector = str(case.get("selector") or "").strip()
        if not selector or selector in seen:
            continue
        seen.add(selector)
        deduped.append(case)
        if len(deduped) >= max(1, int(top_n)):
            break
    return deduped


def extract_trace_assets(output: str) -> dict[str, str | None]:
    def _match(label: str) -> str | None:
        pattern = re.compile(rf"^\s*{re.escape(label)}\s+(.+)$", re.MULTILINE)
        found = pattern.search(output)
        return found.group(1).strip() if found else None

    return {
        "trace_path": _match("trace_path"),
        "trace_rel_path": _match("trace_rel_path"),
        "trace_preview_path": _match("preview_path"),
        "trace_preview_rel_path": _match("preview_rel_path"),
    }


def plot_command(
    selector: str,
    *,
    bot: str,
    trace_sample_period_s: float,
    trace_detail: str,
) -> list[str]:
    return [
        "uv",
        "run",
        "python",
        "main.py",
        "plot",
        selector,
        "--bot",
        bot,
        "--trace-sample-period-s",
        f"{max(0.05, float(trace_sample_period_s)):.3f}",
        "--trace-detail",
        str(trace_detail),
    ]


def _default_plot_workers() -> int:
    return max(1, min(16, int(os.cpu_count() or 1)))


def resolve_plot_workers(value: int | None) -> int:
    if value is None or int(value) <= 0:
        return _default_plot_workers()
    return max(1, int(value))


def _run_plot_command(
    selector: str,
    *,
    bot: str,
    trace_sample_period_s: float,
    trace_detail: str,
) -> dict[str, Any]:
    cmd = plot_command(
        selector,
        bot=bot,
        trace_sample_period_s=trace_sample_period_s,
        trace_detail=trace_detail,
    )
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    wall_clock_s = time.perf_counter() - started
    output = str(proc.stdout or "")
    extracted = extract_trace_assets(output)
    return {
        "command": cmd,
        "exit_code": int(proc.returncode),
        "wall_clock_s": wall_clock_s,
        "output": output,
        **extracted,
    }


def _case_run(
    case: dict[str, Any],
    *,
    index: int,
    bot: str,
    trace_sample_period_s: float,
    trace_detail: str,
    execute: bool,
) -> dict[str, Any]:
    selector = str(case.get("selector") or "").strip()
    cmd = plot_command(
        selector,
        bot=bot,
        trace_sample_period_s=trace_sample_period_s,
        trace_detail=trace_detail,
    )
    if not execute:
        return {
            **case,
            "index": index,
            "command": cmd,
            "exit_code": None,
            "wall_clock_s": None,
            "trace_path": None,
            "trace_rel_path": None,
            "trace_preview_path": None,
            "trace_preview_rel_path": None,
        }

    run = _run_plot_command(
        selector,
        bot=bot,
        trace_sample_period_s=trace_sample_period_s,
        trace_detail=trace_detail,
    )
    return {
        **case,
        "index": index,
        "command": run["command"],
        "exit_code": run["exit_code"],
        "wall_clock_s": run.get("wall_clock_s"),
        "trace_path": run.get("trace_path"),
        "trace_rel_path": run.get("trace_rel_path"),
        "trace_preview_path": run.get("trace_preview_path"),
        "trace_preview_rel_path": run.get("trace_preview_rel_path"),
    }


def assign_case_keys(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    for case in cases:
        selector = str(case.get("selector") or "").strip()
        if selector:
            totals[selector] = totals.get(selector, 0) + 1
    seen: dict[str, int] = {}
    assigned: list[dict[str, Any]] = []
    for case in cases:
        selector = str(case.get("selector") or "").strip()
        if not selector:
            assigned.append(dict(case))
            continue
        instance_id = seen.get(selector, 0) + 1
        seen[selector] = instance_id
        run_key = (
            selector if totals.get(selector, 0) <= 1 else f"{selector}#{instance_id}"
        )
        assigned.append(
            {
                **case,
                "run_instance_id": instance_id,
                "run_key": run_key,
            }
        )
    return assigned


def _default_pack_dir() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return (_REPO_ROOT / "outputs" / "viewer" / "plot-packs" / f"pack_{ts}").resolve()


def _scenario_selector(selector: str) -> str:
    parts = [part for part in str(selector).split(":") if part]
    if len(parts) >= 2 and re.fullmatch(r"-?\d+", parts[-1]):
        return ":".join(parts[:-1])
    return str(selector)


def _validate_case_runs(case_runs: list[dict[str, Any]]) -> None:
    failures: list[str] = []
    for run in case_runs:
        exit_code = run.get("exit_code")
        if exit_code is None:
            continue
        trace_path = _output_path(run.get("trace_path"), repo_root=_REPO_ROOT)
        if int(exit_code) > 1:
            failures.append(f"{run.get('selector')}: exit {exit_code}")
            continue
        if trace_path is None or not trace_path.exists():
            failures.append(f"{run.get('selector')}: missing trace json")
    if failures:
        raise SystemExit(
            "Trace plot-pack generation failed:\n"
            + "\n".join(f"- {item}" for item in failures)
        )


def _build_case_detail_payload(
    run: dict[str, Any],
    *,
    pack_dir: Path,
    outputs_root: Path,
    plotly_rel: str,
) -> tuple[dict[str, Any], str]:
    selector = str(run.get("selector") or "unknown")
    run_key = str(run.get("run_key") or selector).strip() or selector
    trace_path = _output_path(run.get("trace_path"), repo_root=_REPO_ROOT)
    trace_payload = (
        load_json(trace_path) if trace_path is not None and trace_path.exists() else {}
    )
    final_result = dict(trace_payload.get("final_result") or {})
    record = {
        "bot": final_result.get("bot", "pdg"),
        "state": final_result.get("state"),
        "failure_mode": final_result.get("failure_mode"),
        "success": final_result.get("success"),
        "fuel_consumed": final_result.get("fuel_consumed"),
        "time": final_result.get("time"),
        "landing_offset": final_result.get("landing_offset"),
        "avg_speed": final_result.get("avg_speed"),
        "bot_profile_total_ms_per_tick": final_result.get(
            "bot_profile_total_ms_per_tick"
        ),
    }
    detail_path = (pack_dir / "runs" / f"{_sanitize_token(run_key)}.html").resolve()
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    plotly_href = (
        _href_from(detail_path.parent, outputs_root / plotly_rel)
        or f"../../assets/{PLOTLY_FILENAME}"
    )
    trace_href = _href_from(detail_path.parent, trace_path)
    detail_html = render_trace_detail_html(
        title=f"{selector} • Pylander Plot Detail",
        selector=selector,
        scenario_selector=_scenario_selector(selector),
        record=record,
        trace_payload=trace_payload,
        plotly_href=plotly_href,
        top_links=[
            ("plot pack", _href_from(detail_path.parent, pack_dir / "index.html"))
        ],
        raw_links=[("trace json", trace_href)],
        repro_commands=[" ".join(str(part) for part in (run.get("command") or []))],
    )
    detail_path.write_text(detail_html, encoding="utf-8")
    detail_rel = _rel_to_outputs(detail_path, outputs_root=outputs_root)
    return (
        {
            **record,
            "run_key": run_key,
            "run_instance_id": int(run.get("run_instance_id", 1) or 1),
            "detail_path": str(detail_path),
            "detail_rel_path": detail_rel,
        },
        detail_html,
    )


def _render_index_html(
    *,
    pack_id: str,
    cases: list[dict[str, Any]],
    pack_dir: Path,
    outputs_root: Path,
) -> str:
    cards: list[str] = []
    for case in cases:
        selector_value = str(case.get("selector") or "unknown")
        selector = html.escape(selector_value)
        reason = html.escape(str(case.get("reason") or ""))
        severity = html.escape(str(case.get("severity") or ""))
        duplicate_count = sum(
            1 for item in cases if str(item.get("selector") or "") == selector_value
        )
        instance_id = int(case.get("run_instance_id", 1) or 1)
        display_selector = selector
        if duplicate_count > 1:
            display_selector = f"{selector} #{instance_id}"
        detail_path = _output_path(case.get("detail_path"), repo_root=_REPO_ROOT)
        detail_href = _href_from(pack_dir, detail_path)
        preview_path = _output_path(
            case.get("trace_preview_path"), repo_root=_REPO_ROOT
        )
        preview_href = _href_from(pack_dir, preview_path)
        trace_path = _output_path(case.get("trace_path"), repo_root=_REPO_ROOT)
        trace_href = _href_from(pack_dir, trace_path)
        state = html.escape(str(case.get("state") or "-"))
        cards.append(
            '<article class="card">'
            f"<h3>{display_selector}</h3>"
            f'<p class="meta">severity={severity} reason={reason} state={state}</p>'
            + (
                f'<a class="preview" href="{html.escape(detail_href or "#")}"><img src="{html.escape(preview_href)}" alt="{selector}"></a>'
                if preview_href and detail_href
                else '<p class="muted">No preview image</p>'
            )
            + '<p class="links">'
            + " | ".join(
                link
                for link in [
                    f'<a href="{html.escape(detail_href)}">detail</a>'
                    if detail_href
                    else "",
                    f'<a href="{html.escape(trace_href)}">trace json</a>'
                    if trace_href
                    else "",
                ]
                if link
            )
            + "</p>"
            + "</article>"
        )
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Pylander Plot Pack {html.escape(pack_id)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1e8;
      --panel: #fffaf0;
      --ink: #1d1f24;
      --muted: #575f66;
      --accent: #0e6b60;
      --line: #d8cfbf;
      --shadow: rgba(29, 31, 36, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, \"Times New Roman\", serif; color: var(--ink); background: linear-gradient(180deg, #f7f4ec 0%, var(--bg) 100%); }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px 48px; }}
    header, .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 24px var(--shadow); }}
    header {{ padding: 18px 20px; margin-bottom: 18px; }}
    h1, h2, h3 {{ margin: 0 0 10px; font-family: \"Palatino Linotype\", \"Book Antiqua\", Palatino, serif; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    .card {{ padding: 16px; }}
    .meta, .muted, .links {{ color: var(--muted); }}
    .preview img {{ width: 100%; height: auto; display: block; border-radius: 12px; border: 1px solid var(--line); background: #fbf8f1; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Pylander Plot Pack</h1>
      <p class=\"meta\">pack={html.escape(pack_id)} cases={len(cases)}</p>
    </header>
    <section class=\"grid\">
      {"".join(cards) if cards else '<p class="muted">No cases.</p>'}
    </section>
  </main>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build and optionally execute Pylander trace-first plot packs"
    )
    ap.add_argument(
        "--mode", choices=("health", "compare", "focus", "triage"), required=True
    )
    ap.add_argument("--benchmark-json", type=str, default=None)
    ap.add_argument("--compare-json", type=str, default=None)
    ap.add_argument("--selectors", nargs="*", default=[])
    ap.add_argument("--bot", default="pdg")
    ap.add_argument("--top-n", type=int, default=8)
    ap.add_argument("--trace-sample-period-s", type=float, default=0.25)
    ap.add_argument(
        "--trace-detail", choices=("report", "replay", "debug"), default="debug"
    )
    ap.add_argument("--plot-workers", type=int, default=0)
    ap.add_argument("--execute", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--output-manifest", type=str, default=None)
    args = ap.parse_args()

    benchmark_payload = (
        load_json(Path(args.benchmark_json)) if args.benchmark_json else None
    )
    compare_payload = load_json(Path(args.compare_json)) if args.compare_json else None
    if args.mode == "compare" and compare_payload is None:
        raise SystemExit("compare mode requires --compare-json")

    top_n = max(1, int(args.top_n))
    cases: list[dict[str, Any]] = []

    if args.mode == "focus":
        selectors = split_csv(list(args.selectors or []))
        if not selectors:
            raise SystemExit("focus mode requires --selectors")
        for selector in selectors[:top_n]:
            cases.append(
                {
                    "selector": selector,
                    "severity": "manual",
                    "reason": "focus_selector",
                    "evidence": {},
                }
            )
    elif args.mode in {"compare", "triage"}:
        if compare_payload is not None:
            cases.extend(build_cases_from_compare(compare_payload, top_n=top_n))
        if benchmark_payload is not None and len(cases) < top_n:
            records = [
                dict(r)
                for r in (benchmark_payload.get("records") or [])
                if isinstance(r, dict)
            ]
            for case in build_cases_from_records(
                records, top_n=top_n, bot=str(args.bot)
            ):
                if any(
                    str(c.get("selector")) == str(case.get("selector")) for c in cases
                ):
                    continue
                cases.append(case)
                if len(cases) >= top_n:
                    break
    else:
        if benchmark_payload is None:
            raise SystemExit("health mode requires --benchmark-json")
        records = [
            dict(r)
            for r in (benchmark_payload.get("records") or [])
            if isinstance(r, dict)
        ]
        cases = build_cases_from_records(records, top_n=top_n, bot=str(args.bot))

    if not cases:
        raise SystemExit("No plot cases resolved")
    cases = assign_case_keys(cases)

    plot_workers = 1 if not args.execute else resolve_plot_workers(args.plot_workers)
    started_at_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    case_runs: list[dict[str, Any]] = []
    filtered_cases = [
        (idx, case)
        for idx, case in enumerate(cases, start=1)
        if str(case.get("selector") or "").strip()
    ]
    if plot_workers <= 1 or len(filtered_cases) <= 1:
        for idx, case in filtered_cases:
            case_runs.append(
                _case_run(
                    case,
                    index=idx,
                    bot=args.bot,
                    trace_sample_period_s=max(0.05, float(args.trace_sample_period_s)),
                    trace_detail=str(args.trace_detail),
                    execute=bool(args.execute),
                )
            )
    else:
        indexed_runs: dict[int, dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(plot_workers, len(filtered_cases))
        ) as executor:
            future_map = {
                executor.submit(
                    _case_run,
                    case,
                    index=idx,
                    bot=args.bot,
                    trace_sample_period_s=max(0.05, float(args.trace_sample_period_s)),
                    trace_detail=str(args.trace_detail),
                    execute=bool(args.execute),
                ): idx
                for idx, case in filtered_cases
            }
            for future in concurrent.futures.as_completed(future_map):
                run = future.result()
                indexed_runs[int(run["index"])] = run
        case_runs = [indexed_runs[idx] for idx, _case in filtered_cases]

    if args.execute:
        _validate_case_runs(case_runs)

    wall_clock_s = time.perf_counter() - started
    outputs_root = (_REPO_ROOT / "outputs").resolve()
    manifest_path = (
        Path(args.output_manifest).resolve()
        if args.output_manifest
        else (_default_pack_dir() / "manifest.json")
    )
    pack_dir = manifest_path.parent
    pack_dir.mkdir(parents=True, exist_ok=True)
    index_path = (pack_dir / "index.html").resolve()
    pack_id = pack_dir.name
    viewer_assets = ensure_viewer_assets(outputs_root)

    enriched_runs: list[dict[str, Any]] = []
    for run in case_runs:
        case_payload = dict(run)
        trace_path = _output_path(case_payload.get("trace_path"), repo_root=_REPO_ROOT)
        if trace_path is not None and trace_path.exists():
            detail_meta, _detail_html = _build_case_detail_payload(
                case_payload,
                pack_dir=pack_dir,
                outputs_root=outputs_root,
                plotly_rel=str(viewer_assets.get("plotly_rel") or ""),
            )
            case_payload.update(detail_meta)
        enriched_runs.append(case_payload)

    index_html = _render_index_html(
        pack_id=pack_id,
        cases=enriched_runs,
        pack_dir=pack_dir,
        outputs_root=outputs_root,
    )
    index_path.write_text(index_html, encoding="utf-8")

    payload = {
        "mode": args.mode,
        "bot": args.bot,
        "trace_sample_period_s": max(0.05, float(args.trace_sample_period_s)),
        "trace_detail": str(args.trace_detail),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "started_at_utc": started_at_utc,
        "wall_clock_s": wall_clock_s,
        "plot_workers": plot_workers,
        "benchmark_json": args.benchmark_json,
        "compare_json": args.compare_json,
        "index_path": str(index_path),
        "index_rel_path": _rel_to_outputs(index_path, outputs_root=outputs_root),
        "viewer_assets": dict(viewer_assets),
        "cases": enriched_runs,
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(
        "# plot_pack\n"
        f"manifest={manifest_path}\n"
        f"index={index_path}\n"
        f"cases={len(enriched_runs)}\n"
        f"plot_workers={plot_workers}\n"
        f"wall_clock_s={wall_clock_s:.3f}"
    )


__all__ = [
    "assign_case_keys",
    "build_cases_from_compare",
    "build_cases_from_records",
    "extract_trace_assets",
    "main",
    "plot_command",
    "resolve_plot_workers",
]
