from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import (  # noqa: E402
    load_json,
    parse_compare_report_path,
    parse_section_json_path,
    run_command,
    to_float,
    to_int,
    utc_now_iso,
    write_json,
)


def _default_metrics() -> dict[str, Any]:
    return {
        "success_rate": 0.0,
        "success_rate_delta": 0.0,
        "fuel_mean_primary_delta": 0.0,
        "new_global_crashes": 0,
        "compute_avg_total_delta_ms": 0.0,
        "compute_p99_total_delta_ms": 0.0,
        "observation_regressions": 0,
        "notable_global_regression": False,
    }


def _metrics_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    summary = dict(candidate.get("summary") or {})
    return {
        "success_rate": to_float(summary.get("success_rate"), 0.0),
        "success_rate_delta": 0.0,
        "fuel_mean_primary_delta": 0.0,
        "new_global_crashes": to_int(summary.get("crashed"), 0),
        "compute_avg_total_delta_ms": 0.0,
        "compute_p99_total_delta_ms": 0.0,
        "observation_regressions": 0,
        "notable_global_regression": bool(to_int(summary.get("crashed"), 0) > 0),
    }


def _metrics_from_compare(compare: dict[str, Any]) -> dict[str, Any]:
    global_block = dict(compare.get("global") or {})
    summary_delta = dict(global_block.get("summary_delta") or {})
    crash = dict(global_block.get("crash") or {})
    compute = dict(global_block.get("compute") or {})
    compute_deltas = dict(compute.get("deltas") or {})

    avg_total = dict(compute_deltas.get("bot_profile_total_ms_per_tick") or {})
    p99_total = dict(compute_deltas.get("bot_profile_total_ms_per_tick_p99") or {})

    observation_block = dict(compare.get("observation") or {})
    observation_crash = dict(observation_block.get("crash") or {})

    return {
        "success_rate": to_float(
            dict(global_block.get("summary_candidate") or {}).get("success_rate"), 0.0
        ),
        "success_rate_delta": to_float(summary_delta.get("success_rate"), 0.0),
        "fuel_mean_primary_delta": to_float(summary_delta.get("fuel_mean_primary"), 0.0),
        "new_global_crashes": len(list(crash.get("new_crashes") or [])),
        "compute_avg_total_delta_ms": to_float(avg_total.get("delta_abs"), 0.0),
        "compute_p99_total_delta_ms": to_float(p99_total.get("delta_abs"), 0.0),
        "observation_regressions": len(list(observation_crash.get("new_crashes") or [])),
        "notable_global_regression": bool(global_block.get("notable_regression", False)),
    }


def _choose_decision(summary: dict[str, Any]) -> str:
    if to_int(summary.get("new_global_crashes"), 0) > 0:
        return "drop"
    if to_float(summary.get("success_rate_delta"), 0.0) < 0.0:
        return "drop"
    if bool(summary.get("notable_global_regression", False)):
        return "drop"
    if (
        to_float(summary.get("fuel_mean_primary_delta"), 0.0) <= -0.10
        and to_float(summary.get("compute_avg_total_delta_ms"), 0.0) <= 0.10
        and to_float(summary.get("compute_p99_total_delta_ms"), 0.0) <= 0.20
    ):
        return "promote"
    return "iterate"


def _run_validation(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    selectors = [str(s).strip() for s in payload.get("selectors") or [] if str(s).strip()]
    if not selectors:
        raise ValueError("selectors must be non-empty when execute-validation is enabled")

    bot = str(payload.get("bot") or "zem_zev")
    baseline_ref = str(payload.get("baseline_ref") or "").strip()
    bot_config_path = str(payload.get("bot_config_path") or "").strip()

    commands: list[str] = []
    repros: list[str] = []

    sim_cmd = ["uv", "run", "python", "main.py", "sim", selectors[0], "--bot", bot, "--freq", "1"]
    commands.append(" ".join(sim_cmd))

    plot_cmd = [
        "uv",
        "run",
        "python",
        "main.py",
        "plot",
        selectors[0],
        "--bot",
        bot,
        "--plot",
        "all",
        "--plot-output",
        "both",
    ]
    commands.append(" ".join(plot_cmd))

    bench_cmd = [
        "uv",
        "run",
        "python",
        "skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
        "--mode",
        "focused",
        "--selectors",
        *selectors,
        "--seed-spec",
        str(payload.get("seed_spec") or "0-4"),
        "--bot",
        bot,
    ]
    if bot_config_path:
        bench_cmd += ["--bot-config", bot_config_path]
    if baseline_ref:
        bench_cmd += ["--baseline-ref", baseline_ref]

    commands.append(" ".join(bench_cmd))
    code, output = run_command(bench_cmd, cwd=_REPO_ROOT)
    if code != 0:
        raise RuntimeError(f"focused benchmark failed with exit code {code}")

    compare_path = parse_compare_report_path(output)
    if compare_path:
        compare = load_json(compare_path)
        metrics = _metrics_from_compare(compare)
        crash_block = dict(dict(compare.get("global") or {}).get("crash") or {})
        for item in list(crash_block.get("new_crashes") or [])[:3]:
            if not isinstance(item, dict):
                continue
            repro = dict(item.get("repro") or {})
            for key in ("plot", "sim_trace", "sim_profile"):
                val = str(repro.get(key) or "").strip()
                if val and val not in repros:
                    repros.append(val)
        return metrics, commands, repros

    candidate_json = parse_section_json_path(output, "candidate")
    if candidate_json:
        candidate = load_json(candidate_json)
        metrics = _metrics_from_candidate(candidate)
        repros.append(" ".join(sim_cmd))
        repros.append(" ".join(plot_cmd))
        return metrics, commands, repros

    raise RuntimeError("Unable to parse benchmark output paths for arena worker")


def generate_branch_report(payload: dict[str, Any], *, execute_validation: bool = False) -> dict[str, Any]:
    arena_id = str(payload.get("arena_id") or "").strip()
    arena_type = str(payload.get("arena_type") or "").strip().lower()
    branch_id = str(payload.get("branch_id") or "").strip()
    if not arena_id:
        raise ValueError("arena_id is required")
    if arena_type not in {"strategy", "tune"}:
        raise ValueError("arena_type must be strategy or tune")
    if not branch_id:
        raise ValueError("branch_id is required")

    commands: list[str] = []
    top_repros: list[str] = []

    if execute_validation:
        summary, commands, top_repros = _run_validation(payload)
    else:
        summary = _default_metrics()
        raw = payload.get("measured_metrics")
        if isinstance(raw, dict):
            summary.update(raw)

    normalized_summary = {
        "success_rate": to_float(summary.get("success_rate"), 0.0),
        "success_rate_delta": to_float(summary.get("success_rate_delta"), 0.0),
        "fuel_mean_primary_delta": to_float(summary.get("fuel_mean_primary_delta"), 0.0),
        "new_global_crashes": max(0, to_int(summary.get("new_global_crashes"), 0)),
        "compute_avg_total_delta_ms": to_float(summary.get("compute_avg_total_delta_ms"), 0.0),
        "compute_p99_total_delta_ms": to_float(summary.get("compute_p99_total_delta_ms"), 0.0),
        "observation_regressions": max(0, to_int(summary.get("observation_regressions"), 0)),
        "notable_global_regression": bool(summary.get("notable_global_regression", False)),
    }

    decision = _choose_decision(normalized_summary)
    note = str(payload.get("hypothesis") or "").strip()
    notes = note or "no hypothesis provided"

    report = {
        "contract": "arena_branch_report.v1",
        "arena_id": arena_id,
        "arena_type": arena_type,
        "branch_id": branch_id,
        "decision": decision,
        "summary": normalized_summary,
        "top_repros": [str(c).strip() for c in top_repros if str(c).strip()],
        "commands": [str(c).strip() for c in commands if str(c).strip()],
        "notes": notes,
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(report, "arena_branch_report.v1")
    return report


def _notes_text(payload: dict[str, Any], report: dict[str, Any]) -> str:
    lines = [
        f"arena_id: {report['arena_id']}",
        f"arena_type: {report['arena_type']}",
        f"branch_id: {report['branch_id']}",
        f"hypothesis: {str(payload.get('hypothesis') or 'n/a').strip()}",
        f"decision: {report['decision']}",
        "",
        "summary:",
    ]
    summary = dict(report.get("summary") or {})
    for key in (
        "success_rate",
        "success_rate_delta",
        "fuel_mean_primary_delta",
        "new_global_crashes",
        "compute_avg_total_delta_ms",
        "compute_p99_total_delta_ms",
        "observation_regressions",
        "notable_global_regression",
    ):
        lines.append(f"- {key}: {summary.get(key)}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Execute one Pylander arena branch and emit a normalized report")
    ap.add_argument("--input", required=True, help="Input JSON payload")
    ap.add_argument("--output", required=True, help="Output report JSON")
    ap.add_argument(
        "--execute-validation",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Run focused benchmark validation commands",
    )
    args = ap.parse_args()

    payload = load_json(args.input)
    report = generate_branch_report(payload, execute_validation=bool(args.execute_validation))

    arena_id = str(report["arena_id"])
    branch_id = str(report["branch_id"])
    artifact_dir = (_REPO_ROOT / "outputs" / "arena" / arena_id / branch_id).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "report.json"
    notes_path = artifact_dir / "notes.md"
    write_json(report_path, report)
    notes_path.write_text(_notes_text(payload, report), encoding="utf-8")

    out_path = Path(args.output).resolve()
    if out_path != report_path:
        write_json(out_path, report)

    print(f"# arena_branch_report\njson={out_path}\nartifact_report={report_path}\nartifact_notes={notes_path}")


if __name__ == "__main__":
    main()
