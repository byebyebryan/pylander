from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_ROOT = (_REPO_ROOT / ".agents").resolve()
for candidate in (_AGENTS_ROOT, _REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import load_json, to_float, to_int, utc_now_iso, write_json  # noqa: E402


def _route_scores(payload: dict[str, Any]) -> tuple[int, int, dict[str, bool], dict[str, bool]]:
    metrics = dict(payload.get("recent_metrics") or {})

    candidate_directions = max(0, to_int(metrics.get("candidate_directions"), 1))
    viable_directions = max(0, to_int(metrics.get("viable_directions"), candidate_directions))
    loop_plateau_iterations = max(0, to_int(metrics.get("loop_plateau_iterations"), 0))
    last_fuel_delta = to_float(metrics.get("last_fuel_mean_primary_delta"), 0.0)
    compute_avg_delta = to_float(metrics.get("compute_avg_total_delta_ms"), 0.0)
    compute_p99_delta = to_float(metrics.get("compute_p99_total_delta_ms"), 0.0)
    selector_success_stddev = to_float(metrics.get("selector_success_rate_stddev"), 0.0)
    selector_fuel_cv = to_float(metrics.get("selector_fuel_cv"), 0.0)
    logic_coupled = bool(metrics.get("logic_coupled", False))

    arena_flags = {
        "multiple_directions": candidate_directions >= 2,
        "recent_loops_plateaued": loop_plateau_iterations >= 2 and abs(last_fuel_delta) < 0.50,
        "objective_conflict": bool(metrics.get("objective_conflict", False))
        or (last_fuel_delta < -0.25 and (compute_avg_delta > 0.10 or compute_p99_delta > 0.20)),
        "selector_divergence": bool(metrics.get("selector_divergence", False))
        or (selector_success_stddev >= 0.05 or selector_fuel_cv >= 0.15),
    }
    loop_flags = {
        "narrow_local_tuning": candidate_directions <= 1,
        "logic_coupled_with_code": logic_coupled,
        "single_viable_direction": viable_directions <= 1,
    }

    arena_score = sum(1 for value in arena_flags.values() if value)
    loop_score = sum(1 for value in loop_flags.values() if value)
    return arena_score, loop_score, arena_flags, loop_flags


def _choose_route(payload: dict[str, Any]) -> tuple[str, str, list[str], list[str], dict[str, float]]:
    forced = str(payload.get("tuning_route") or "auto").strip().lower()
    if forced not in {"auto", "arena", "loop"}:
        raise ValueError("tuning_route must be one of: auto, arena, loop")

    arena_score, loop_score, arena_flags, loop_flags = _route_scores(payload)
    measured: list[str] = []
    inferred: list[str] = []
    triggered: list[str] = []

    for key, value in arena_flags.items():
        if value:
            triggered.append(key)
            measured.append(f"arena:{key}")
    for key, value in loop_flags.items():
        if value:
            triggered.append(key)
            measured.append(f"loop:{key}")

    if forced in {"arena", "loop"}:
        inferred.append(f"manual_override:{forced}")
        return forced, "high", triggered, measured + inferred, {
            "arena": float(arena_score),
            "loop": float(loop_score),
        }

    if arena_score == 0 and loop_score == 0:
        inferred.append("weak_evidence_defaults_to_loop")
        return "loop", "low", triggered, measured + inferred, {
            "arena": float(arena_score),
            "loop": float(loop_score),
        }

    if arena_score > loop_score:
        route = "arena"
    elif loop_score > arena_score:
        route = "loop"
    else:
        route = "arena" if any(
            arena_flags[k] for k in ("objective_conflict", "selector_divergence", "multiple_directions")
        ) else "loop"
        inferred.append("tie_breaker_applied")

    delta = abs(arena_score - loop_score)
    confidence = "high" if delta >= 2 else ("medium" if delta == 1 else "low")
    return route, confidence, triggered, measured, {
        "arena": float(arena_score),
        "loop": float(loop_score),
    }


def route_tuning(payload: dict[str, Any]) -> dict[str, Any]:
    strategy_winner_ref = str(payload.get("strategy_winner_ref") or "").strip()
    if not strategy_winner_ref:
        raise ValueError("strategy_winner_ref is required")

    selectors_raw = payload.get("focused_selectors")
    if not isinstance(selectors_raw, list) or not selectors_raw:
        raise ValueError("focused_selectors must be a non-empty list")
    selectors = [str(item).strip() for item in selectors_raw if str(item).strip()]
    if not selectors:
        raise ValueError("focused_selectors must contain at least one non-empty selector")

    baseline_ref = str(payload.get("baseline_ref") or "main").strip() or "main"
    recommended_route, confidence, triggered, measured, scores = _choose_route(payload)

    if recommended_route == "arena":
        cmd = (
            "uv run python .agents/skills/pylander-tune-orchestrator/scripts/run_tune_arena.py "
            "--input outputs/agents/skills/pylander-tune-orchestrator/input.json "
            "--output outputs/agents/skills/pylander-tune-orchestrator/report.json"
        )
        target_skill = "pylander-tune-orchestrator"
        handoff_payload: dict[str, Any] = {
            "strategy_winner_ref": strategy_winner_ref,
            "focused_selectors": selectors,
            "baseline_ref": baseline_ref,
            "bot": str(payload.get("bot") or "pdg"),
        }
    else:
        cmd = (
            "uv run python .agents/skills/pylander-tune-loop-manager/scripts/run_tune_loop.py "
            "--input outputs/agents/skills/pylander-tune-loop-manager/input.json "
            "--output outputs/agents/skills/pylander-tune-loop-manager/report.json"
        )
        target_skill = "pylander-tune-loop-manager"
        handoff_payload = {
            "selector_scope": selectors,
            "baseline_ref": baseline_ref,
            "profile": str(payload.get("profile") or "standard"),
            "bot": str(payload.get("bot") or "pdg"),
        }

    out: dict[str, Any] = {
        "contract": "route_decision.v1",
        "recommended_route": recommended_route,
        "confidence": confidence,
        "triggered_conditions": sorted(triggered),
        "route_rationale": {
            "measured_signals": measured,
            "inferred_signals": [
                f"strategy_winner_ref={strategy_winner_ref}",
                f"selector_count={len(selectors)}",
            ],
        },
        "scores": scores,
        "execution_plan": [
            {
                "step": "run_next_skill",
                "command": cmd,
            }
        ],
        "handoff_payload": {
            "target_skill": target_skill,
            "payload": handoff_payload,
        },
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(out, "route_decision.v1")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Route Pylander tuning between tune-arena and tune-loop")
    ap.add_argument("--input", required=True, help="Input JSON payload")
    ap.add_argument("--output", required=True, help="Output route decision JSON")
    args = ap.parse_args()

    payload = load_json(args.input)
    report = route_tuning(payload)
    write_json(args.output, report)
    print(f"# route_decision\njson={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
