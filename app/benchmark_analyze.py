from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.benchmark_context import analysis_sidecar_path, discover_compare_path, load_intent
from app.benchmark_context import load_json as load_json_file
from core.selector_codec import render_record_selector

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_delta(value: Any, *, digits: int = 3) -> str:
    number = _coerce_float(value)
    if number is None:
        return "n/a"
    return f"{number:+.{digits}f}"


def _run_repro_commands(record: dict[str, Any], *, bot: str) -> list[str]:
    selector = render_record_selector(record)
    return [
        f"uv run python main.py plot {selector} --bot {bot}",
        f"uv run python main.py sim {selector} --bot {bot} --freq 1",
        f"PYLANDER_BOT_PROFILE=1 uv run python main.py sim {selector} --bot {bot} --freq 1",
    ]


def _top_failed_records(candidate_payload: dict[str, Any], *, bot: str) -> list[str]:
    commands: list[str] = []
    for record in candidate_payload.get("records") or []:
        if not isinstance(record, dict):
            continue
        if bool(record.get("success", False)):
            continue
        commands.extend(_run_repro_commands(record, bot=bot))
        if len(commands) >= 3:
            break
    return commands[:3]


def _measure_evidence(
    *,
    candidate_payload: dict[str, Any],
    compare_payload: dict[str, Any] | None,
) -> list[str]:
    summary = dict(candidate_payload.get("summary") or {})
    evidence = [
        "candidate success_rate="
        f"{_coerce_float(summary.get('success_rate')):.3f}"
        if _coerce_float(summary.get("success_rate")) is not None
        else "candidate success_rate=n/a",
        f"candidate runs={int(summary.get('runs', 0) or 0)}",
        f"candidate crashed={int(summary.get('crashed', 0) or 0)}",
    ]
    if compare_payload is None:
        return evidence

    global_block = dict(compare_payload.get("global") or {})
    summary_delta = dict(global_block.get("summary_delta") or {})
    crash_block = dict(global_block.get("crash") or {})
    compute_block = dict(global_block.get("compute") or {})
    evidence.extend(
        [
            "global delta success_rate="
            f"{_format_delta(summary_delta.get('success_rate'))}",
            f"global delta crashed={_format_delta(summary_delta.get('crashed'), digits=0)}",
            "global delta fuel_mean_primary="
            f"{_format_delta(summary_delta.get('fuel_mean_primary'))}",
            f"new global crashes={len(crash_block.get('new_crashes') or [])}",
        ]
    )
    if compute_block.get("available"):
        deltas = dict(compute_block.get("deltas") or {})
        total_avg = dict(deltas.get("bot_profile_total_ms_per_tick") or {})
        total_p99 = dict(deltas.get("bot_profile_total_ms_per_tick_p99") or {})
        evidence.append(
            "compute total avg ms/tick="
            f"{_format_delta(total_avg.get('delta_abs'))}"
        )
        evidence.append(
            "compute total p99 ms/tick="
            f"{_format_delta(total_p99.get('delta_abs'))}"
        )
    return evidence


def _affected_levels(compare_payload: dict[str, Any]) -> list[str]:
    levels: list[str] = []
    for item in dict(compare_payload.get("global") or {}).get("crash", {}).get(
        "new_crashes", []
    ) or []:
        if isinstance(item, dict):
            levels.append(str(item.get("level") or "").strip())
    for row in dict(compare_payload.get("global") or {}).get("worst_scenarios") or []:
        if not isinstance(row, dict):
            continue
        scenario = str(row.get("scenario") or "").strip()
        if ":" in scenario:
            levels.append(scenario.split(":", 1)[0])
    return [item for item, _count in Counter(levels).most_common() if item]


def _likely_causes(
    *,
    compare_payload: dict[str, Any] | None,
    intent_payload: dict[str, Any] | None,
) -> tuple[list[str], str]:
    repo_context = dict((intent_payload or {}).get("repo_context") or {})
    touched_areas = [str(item) for item in repo_context.get("touched_areas") or []]
    baseline_plan = dict((intent_payload or {}).get("baseline_plan") or {})
    causes: list[str] = []
    confidence = "medium"

    if compare_payload is None:
        if touched_areas:
            causes.append(
                "Candidate-only run; likely impact areas come from the current repo changes: "
                + ", ".join(touched_areas)
            )
        else:
            causes.append(
                "Candidate-only run with no baseline compare; cause inference is limited until a compare is available."
            )
            confidence = "low"
        return causes, confidence

    affected_levels = _affected_levels(compare_payload)
    global_block = dict(compare_payload.get("global") or {})
    crash_block = dict(global_block.get("crash") or {})
    compute_block = dict(global_block.get("compute") or {})

    if touched_areas and set(touched_areas).issubset(
        {"benchmark_tooling", "docs", "skills", "tests"}
    ):
        causes.append(
            "Current changes are limited to docs, skills, tests, or benchmark tooling, so any behavioral delta is more likely measurement noise or benchmark/reporting drift than sim logic."
        )
        confidence = "medium"
    if "bot_logic" in touched_areas:
        if affected_levels:
            causes.append(
                "Changed files include bot logic, and the strongest regressions cluster in "
                + ", ".join(affected_levels[:3])
                + ", which points to guidance or phase-control behavior."
            )
        else:
            causes.append(
                "Changed files include bot logic, so efficiency or success-rate movement is likely coming from guidance/control behavior."
            )
    if "level_logic" in touched_areas:
        causes.append(
            "Changed files include level or scenario definitions, so shifted spawn/setup conditions may explain any selector-local deltas."
        )
    if any(area in touched_areas for area in ("core_runtime", "app_runtime")):
        causes.append(
            "Changed files include runtime or evaluation code, which can affect both outcome metrics and profiling numbers across multiple selectors."
        )
    if compute_block.get("notable_regression"):
        causes.append(
            "Compare data shows a notable compute regression, so some of the change is likely runtime or bot hot-path cost rather than pure flight behavior."
        )
    if crash_block.get("new_crashes"):
        causes.append(
            "New global crashes were introduced relative to baseline, so the most likely root cause is stability regression in the changed behavior-affecting areas."
        )
        confidence = "high" if touched_areas else confidence
    if baseline_plan.get("strategy") == "auto" and baseline_plan.get("skipped_commits"):
        causes.append(
            "Baseline selection skipped benchmark-irrelevant commits, so this compare is anchored to the last likely behavior-affecting ancestor rather than the nearest commit."
        )
    if not causes:
        causes.append(
            "Measured deltas are present, but changed-file areas do not point to a single clear cause yet."
        )
        confidence = "low"
    return causes[:4], confidence


def build_analysis_payload(
    *,
    candidate_payload: dict[str, Any],
    compare_payload: dict[str, Any] | None,
    intent_payload: dict[str, Any] | None,
    candidate_json_path: Path,
) -> dict[str, Any]:
    compare_present = compare_payload is not None
    verdict = "investigate"
    summary = "Candidate benchmark analyzed without a baseline compare."
    follow_ups: list[str] = []

    if compare_present:
        global_block = dict(compare_payload.get("global") or {})
        summary_delta = dict(global_block.get("summary_delta") or {})
        crash_block = dict(global_block.get("crash") or {})
        compute_block = dict(global_block.get("compute") or {})
        success_delta = _coerce_float(summary_delta.get("success_rate")) or 0.0
        fuel_delta = _coerce_float(summary_delta.get("fuel_mean_primary")) or 0.0
        new_crashes = len(crash_block.get("new_crashes") or [])
        notable = bool(compare_payload.get("notable_regression", False))
        compute_notable = bool(compute_block.get("notable_regression", False))
        if notable or new_crashes > 0 or success_delta < -0.01:
            verdict = "regression"
            summary = (
                f"Global regressions detected: success_rate {_format_delta(success_delta)}"
                f", new_crashes={new_crashes}, fuel_mean_primary {_format_delta(fuel_delta)}."
            )
        elif success_delta > 0.01 or (fuel_delta < -0.25 and not compute_notable):
            verdict = "improvement"
            summary = (
                f"Global results improved: success_rate {_format_delta(success_delta)}"
                f", fuel_mean_primary {_format_delta(fuel_delta)}."
            )
        elif compute_notable:
            verdict = "mixed"
            summary = (
                "Outcome metrics are broadly stable, but compute cost regressed enough to warrant investigation."
            )
        else:
            near_zero = abs(success_delta) <= 0.01 and abs(fuel_delta) <= 0.25 and new_crashes == 0
            verdict = "no_change" if near_zero else "mixed"
            summary = (
                "Compare completed without a notable global regression."
                if verdict == "no_change"
                else "Results moved in mixed directions without a clear single verdict."
            )
        for item in crash_block.get("new_crashes") or []:
            if not isinstance(item, dict):
                continue
            repro = dict(item.get("repro") or {})
            for key in ("plot", "sim_trace", "sim_profile"):
                command = str(repro.get(key) or "").strip()
                if command and command not in follow_ups:
                    follow_ups.append(command)
                if len(follow_ups) >= 3:
                    break
            if len(follow_ups) >= 3:
                break

    bot = str(
        dict((intent_payload or {}).get("run_plan") or {}).get("bot")
        or dict((candidate_payload.get("records") or [{}])[0]).get("bot")
        or "pdg"
    )
    if not follow_ups:
        follow_ups = _top_failed_records(candidate_payload, bot=bot)
    causes, confidence = _likely_causes(
        compare_payload=compare_payload,
        intent_payload=intent_payload,
    )
    evidence = _measure_evidence(
        candidate_payload=candidate_payload,
        compare_payload=compare_payload,
    )

    return {
        "schema": "pylander.benchmark.analysis.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_json": str(candidate_json_path.resolve()),
        "compare_present": compare_present,
        "verdict": verdict,
        "summary": summary,
        "measured_evidence": evidence,
        "likely_causes": causes,
        "confidence": confidence,
        "follow_ups": follow_ups,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Analyze benchmark artifacts and write a structured outcome sidecar"
    )
    ap.add_argument("--candidate-json", required=True)
    ap.add_argument("--compare-json", default=None)
    ap.add_argument("--intent-json", default=None)
    ap.add_argument("--output-json", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    candidate_json = Path(args.candidate_json).expanduser()
    if not candidate_json.is_absolute():
        candidate_json = (_REPO_ROOT / candidate_json).resolve()
    if not candidate_json.exists():
        raise SystemExit(f"Candidate benchmark JSON not found: {candidate_json}")

    compare_json: Path | None = None
    if str(args.compare_json or "").strip():
        compare_json = Path(str(args.compare_json)).expanduser()
        if not compare_json.is_absolute():
            compare_json = (_REPO_ROOT / compare_json).resolve()
    else:
        compare_json = discover_compare_path(candidate_json)
    if compare_json is not None and not compare_json.exists():
        raise SystemExit(f"Compare JSON not found: {compare_json}")

    intent_json: Path | None = None
    if str(args.intent_json or "").strip():
        intent_json = Path(str(args.intent_json)).expanduser()
        if not intent_json.is_absolute():
            intent_json = (_REPO_ROOT / intent_json).resolve()
    else:
        sibling = candidate_json.with_name(f"{candidate_json.stem}.intent.json")
        if sibling.exists():
            intent_json = sibling

    output_json = (
        Path(str(args.output_json)).expanduser().resolve()
        if str(args.output_json or "").strip()
        else analysis_sidecar_path(candidate_json)
    )
    candidate_payload = load_json_file(candidate_json)
    compare_payload = load_json_file(compare_json) if compare_json is not None else None
    intent_payload = load_intent(intent_json) if intent_json is not None else None
    payload = build_analysis_payload(
        candidate_payload=candidate_payload,
        compare_payload=compare_payload,
        intent_payload=intent_payload,
        candidate_json_path=candidate_json,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("# analysis")
    print(f"json={output_json}")
    print(f"verdict={payload['verdict']}")
    print(f"summary={payload['summary']}")


__all__ = ["build_analysis_payload", "build_parser", "main"]


if __name__ == "__main__":
    main()
