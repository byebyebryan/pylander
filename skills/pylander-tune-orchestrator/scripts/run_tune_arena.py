from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills.lib.arena import hard_gate, rank_score  # noqa: E402
from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import load_json, to_float, utc_now_iso, write_json  # noqa: E402


_WORKER_SCRIPT = (_REPO_ROOT / "skills" / "pylander-arena-branch-runner" / "scripts" / "run_arena_branch.py").resolve()


def _resolve_report_for_branch(
    *,
    arena_id: str,
    branch: dict[str, Any],
    execute_workers: bool,
) -> dict[str, Any]:
    inline = branch.get("inline_report")
    if isinstance(inline, dict):
        return dict(inline)

    report_path = str(branch.get("report_path") or "").strip()
    if report_path:
        return load_json(report_path)

    worker_input = branch.get("worker_input")
    if execute_workers and isinstance(worker_input, dict):
        branch_id = str(worker_input.get("branch_id") or branch.get("branch_id") or "").strip()
        if not branch_id:
            raise ValueError("branch_id is required when executing worker_input")
        artifact_dir = (_REPO_ROOT / "outputs" / "arena" / arena_id / branch_id).resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        input_path = artifact_dir / "worker_input.json"
        output_path = artifact_dir / "report.json"

        payload = dict(worker_input)
        payload["arena_id"] = arena_id
        payload["arena_type"] = "tune"
        input_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        cmd = [
            sys.executable,
            str(_WORKER_SCRIPT),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--no-execute-validation",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(_REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"arena worker failed for branch '{branch_id}' with exit code {proc.returncode}\n{proc.stdout}"
            )
        return load_json(output_path)

    raise ValueError("Each tune branch must provide report_path, inline_report, or executable worker_input")


def run_tune_arena(payload: dict[str, Any], *, execute_workers: bool) -> dict[str, Any]:
    arena_id = str(payload.get("arena_id") or "").strip()
    if not arena_id:
        raise ValueError("arena_id is required")

    branches_raw = payload.get("branches")
    if not isinstance(branches_raw, list) or not branches_raw:
        raise ValueError("branches must be a non-empty list")

    selectors = [str(s).strip() for s in payload.get("focused_selectors") or [] if str(s).strip()]
    bot = str(payload.get("bot") or "zem_zev")
    baseline_ref = str(payload.get("baseline_ref") or "main").strip() or "main"

    rows: list[dict[str, Any]] = []
    for item in branches_raw:
        if not isinstance(item, dict):
            raise ValueError("branches entries must be objects")
        report = _resolve_report_for_branch(arena_id=arena_id, branch=item, execute_workers=execute_workers)
        branch_id = str(report.get("branch_id") or item.get("branch_id") or "").strip()
        if not branch_id:
            raise ValueError("branch report is missing branch_id")
        summary = dict(report.get("summary") or {})
        gate = hard_gate(summary)
        score = rank_score(summary) if gate.passed else -1_000_000.0

        rows.append(
            {
                "branch_id": branch_id,
                "worker_decision": str(report.get("decision") or "iterate"),
                "passed_hard_gates": gate.passed,
                "hard_gate_failures": list(gate.failures),
                "rank_score": float(score),
                "summary": {
                    "success_rate": to_float(summary.get("success_rate"), 0.0),
                    "success_rate_delta": to_float(summary.get("success_rate_delta"), 0.0),
                    "fuel_mean_primary_delta": to_float(summary.get("fuel_mean_primary_delta"), 0.0),
                    "new_global_crashes": int(summary.get("new_global_crashes", 0) or 0),
                    "compute_avg_total_delta_ms": to_float(
                        summary.get("compute_avg_total_delta_ms"), 0.0
                    ),
                    "compute_p99_total_delta_ms": to_float(
                        summary.get("compute_p99_total_delta_ms"), 0.0
                    ),
                    "observation_regressions": int(summary.get("observation_regressions", 0) or 0),
                    "notable_global_regression": bool(
                        summary.get("notable_global_regression", False)
                    ),
                },
            }
        )

    rows.sort(key=lambda row: (row["passed_hard_gates"], row["rank_score"]), reverse=True)
    winner = next(
        (
            row
            for row in rows
            if bool(row["passed_hard_gates"]) and str(row["worker_decision"]) != "drop"
        ),
        None,
    )

    if winner is None:
        outcome = "no_winner"
        winner_branch_id = ""
        no_winner_reason = "No tune branch passed hard gates and promote/iterate criteria"
        handoff = {
            "target_skill": "none",
            "payload": {
                "reason": no_winner_reason,
                "recommended_action": "redesign_tuning_branch_plan",
            },
        }
    else:
        outcome = "winner"
        winner_branch_id = str(winner["branch_id"])
        no_winner_reason = ""
        handoff = {
            "target_skill": "pylander-tune-loop-manager",
            "payload": {
                "selector_scope": selectors,
                "profile": "light",
                "baseline_ref": baseline_ref,
                "bot": bot,
                "winner_branch_id": winner_branch_id,
            },
        }

    out = {
        "contract": "arena_scoreboard.v1",
        "arena_id": arena_id,
        "arena_type": "tune",
        "outcome": outcome,
        "winner_branch_id": winner_branch_id,
        "no_winner_reason": no_winner_reason,
        "branches": rows,
        "next_step_handoff": handoff,
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(out, "arena_scoreboard.v1")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Pylander tune arena ranking")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument(
        "--execute-workers",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Execute worker inputs that do not already have reports",
    )
    args = ap.parse_args()

    payload = load_json(args.input)
    report = run_tune_arena(payload, execute_workers=bool(args.execute_workers))

    out_path = write_json(args.output, report)
    artifact_path = (
        _REPO_ROOT / "outputs" / "arena" / str(report["arena_id"]) / "scoreboard.tune.json"
    ).resolve()
    write_json(artifact_path, report)
    print(f"# tune_arena\njson={out_path}\nartifact={artifact_path}")


if __name__ == "__main__":
    main()
