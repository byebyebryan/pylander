from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import load_json, to_float, to_int, utc_now_iso, write_json  # noqa: E402


_PROFILE_DEFAULTS = {
    "light": {"max_iterations": 2, "seed_spec": "0-2"},
    "standard": {"max_iterations": 4, "seed_spec": "0-4"},
    "extensive": {"max_iterations": 6, "seed_spec": "0-9"},
}


def _normalize_scope(raw: Any) -> list[str]:
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, list):
        out = [str(item).strip() for item in raw if str(item).strip()]
        return out
    return []


def run_tune_loop(payload: dict[str, Any]) -> dict[str, Any]:
    profile = str(payload.get("profile") or "standard").strip().lower()
    if profile not in _PROFILE_DEFAULTS:
        raise ValueError("profile must be one of: light, standard, extensive")

    selector_scope = _normalize_scope(payload.get("selector_scope"))
    if not selector_scope:
        raise ValueError("selector_scope is required")

    defaults = dict(_PROFILE_DEFAULTS[profile])
    max_iterations = max(1, to_int(payload.get("max_iterations"), defaults["max_iterations"]))
    seed_spec = str(payload.get("seed_spec") or defaults["seed_spec"]).strip() or defaults["seed_spec"]

    max_new_crashes = max(0, to_int(payload.get("max_new_crashes"), 0))
    min_success_rate = to_float(payload.get("min_success_rate"), 0.0)
    fuel_target_delta = to_float(payload.get("fuel_target_delta"), -0.10)
    compute_avg_guard = to_float(payload.get("compute_avg_guardrail_ms"), 0.10)
    compute_p99_guard = to_float(payload.get("compute_p99_guardrail_ms"), 0.20)

    iterations_raw = payload.get("iterations")
    if iterations_raw is None:
        iterations_raw = []
    if not isinstance(iterations_raw, list):
        raise ValueError("iterations must be a list when provided")

    iteration_rows: list[dict[str, Any]] = []
    final_decision = "no_change"

    for idx, entry in enumerate(iterations_raw[:max_iterations], start=1):
        if not isinstance(entry, dict):
            continue
        metrics = {
            "success_rate": to_float(entry.get("success_rate"), 0.0),
            "success_rate_delta": to_float(entry.get("success_rate_delta"), 0.0),
            "fuel_mean_primary_delta": to_float(entry.get("fuel_mean_primary_delta"), 0.0),
            "new_global_crashes": max(0, to_int(entry.get("new_global_crashes"), 0)),
            "compute_avg_total_delta_ms": to_float(entry.get("compute_avg_total_delta_ms"), 0.0),
            "compute_p99_total_delta_ms": to_float(entry.get("compute_p99_total_delta_ms"), 0.0),
        }

        blocker = (
            metrics["new_global_crashes"] > max_new_crashes
            or metrics["success_rate"] < min_success_rate
            or metrics["compute_avg_total_delta_ms"] > compute_avg_guard
            or metrics["compute_p99_total_delta_ms"] > compute_p99_guard
        )
        if blocker:
            decision = "abort"
            final_decision = "hard_blocker"
        elif metrics["fuel_mean_primary_delta"] <= fuel_target_delta:
            decision = "keep"
            if final_decision != "hard_blocker":
                final_decision = "goals_met"
        else:
            decision = "adjust"

        iteration_rows.append(
            {
                "iteration": idx,
                "decision": decision,
                "metrics": metrics,
            }
        )

        if decision == "abort":
            break

    if final_decision == "no_change":
        if len(iteration_rows) >= max_iterations and max_iterations > 0:
            final_decision = "iteration_budget_exhausted"
        elif not iteration_rows:
            final_decision = "no_change"
        else:
            final_decision = "iteration_budget_exhausted"

    if final_decision in {"goals_met", "iteration_budget_exhausted"}:
        next_handoff = {
            "target_skill": "pylander-regression-analyzer",
            "payload": {
                "mode": str(payload.get("regression_mode") or "quick"),
                "baseline_ref": str(payload.get("baseline_ref") or "main"),
                "bot": str(payload.get("bot") or "pdg"),
            },
        }
    else:
        next_handoff = {
            "target_skill": "none",
            "payload": {
                "reason": final_decision,
            },
        }

    out = {
        "contract": "tune_loop_report.v1",
        "profile": profile,
        "selector_scope": selector_scope,
        "budget": {
            "max_iterations": max_iterations,
            "seed_spec": seed_spec,
        },
        "iterations": iteration_rows,
        "final_decision": final_decision,
        "next_step_handoff": next_handoff,
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(out, "tune_loop_report.v1")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a bounded Pylander tuning decision loop")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    payload = load_json(args.input)
    report = run_tune_loop(payload)
    out_path = write_json(args.output, report)
    print(f"# tune_loop\njson={out_path}")


if __name__ == "__main__":
    main()
