from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.selector import render_record_selector, render_selector  # noqa: E402
from core.eval_schema import HEADLESS_RESULT_FIELDS  # noqa: E402
from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import (  # noqa: E402
    load_json,
    to_float,
    to_int,
    utc_now_iso,
    write_json,
)


_COMPACT_RESULT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*?)(None|True|False|-?[0-9].*)$")
_BOT_PROF_RE = re.compile(
    r"ticks=(?P<ticks>\d+)"
    r".*?passive=(?P<passive>[0-9.]+)ms/t"
    r"(?:.*?active=(?P<active>[0-9.]+)ms/t)?"
    r"(?:.*?query=(?P<query>[0-9.]+)ms/t)?"
    r".*?update=(?P<update>[0-9.]+)ms/t"
    r".*?total=(?P<total>[0-9.]+)ms/t"
)
_PHASE_RE = re.compile(r"\bph:(?P<phase>[a-z_]+)\b")
_SOLVE_MS_RE = re.compile(r"\bslv:(?P<ms>[0-9.]+)ms\b")
_RESULT_LABELS: tuple[str, ...] = tuple(
    sorted((field.capitalize() for field in HEADLESS_RESULT_FIELDS), key=len, reverse=True)
)


def _selector_from_record(record: dict[str, Any]) -> str:
    return render_record_selector(record)


def _selector_from_triplet(
    level: Any,
    scenario: Any,
    seed: Any,
    *,
    eval_goal: Any = "landing",
) -> str:
    try:
        seed_token = str(int(seed))
    except (TypeError, ValueError):
        seed_token = "0"
    return render_selector(
        level_name=str(level or "").strip() or "unknown",
        scenario_name=str(scenario or "").strip() or None,
        goal=str(eval_goal or "landing").strip().lower() or "landing",
        seed_token=seed_token,
    )


def _repro_commands(
    selector: str,
    *,
    bot: str,
    include_debug: bool,
) -> list[str]:
    selector_token = str(selector or "").strip()
    if not selector_token:
        return []

    commands = [
        (
            "uv run python main.py plot "
            f"{selector_token} --bot {bot} "
            "--plot all --plot-output both --plot-max-side-px 1800"
        ),
        f"uv run python main.py sim {selector_token} --bot {bot} --freq 1",
        (
            "PYLANDER_BOT_PROFILE=1 uv run python main.py sim "
            f"{selector_token} --bot {bot} --freq 1"
        ),
    ]
    if include_debug:
        commands.append(
            "PYLANDER_ZEM_DEBUG_SETUP=1 uv run python main.py sim "
            f"{selector_token} --bot {bot} --freq 1"
        )
    return commands


def _parse_scalar(value: str) -> Any:
    token = str(value or "").strip()
    if not token:
        return ""
    if token == "None":
        return None
    if token == "True":
        return True
    if token == "False":
        return False
    try:
        if token.startswith("0") and len(token) > 1 and token[1].isdigit():
            return float(token)
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token


def _parse_final_results(lines: list[str]) -> dict[str, Any]:
    in_results = False
    parsed: dict[str, Any] = {}

    for line in lines:
        stripped = line.strip()
        if stripped == "FINAL RESULTS":
            in_results = True
            continue
        if not in_results:
            continue
        if not stripped:
            continue
        if set(stripped) == {"="}:
            continue

        match = re.match(r"^([A-Za-z0-9_]+)\s+(.+)$", stripped)
        if match:
            key = str(match.group(1)).strip()
            raw_value = str(match.group(2)).strip()
            parsed[key] = _parse_scalar(raw_value)
            continue

        for key in _RESULT_LABELS:
            if not stripped.startswith(key):
                continue
            if len(stripped) <= len(key):
                continue
            raw_value = stripped[len(key) :].strip()
            if raw_value:
                parsed[key] = _parse_scalar(raw_value)
            break
        else:
            compact = _COMPACT_RESULT_RE.match(stripped)
            if compact:
                key = str(compact.group(1)).strip()
                raw_value = str(compact.group(2)).strip()
                parsed[key] = _parse_scalar(raw_value)

    return parsed


def _parse_sim_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    selector = ""
    for line in lines:
        match = re.match(r"^Selector:\s+(.+)$", line.strip())
        if match:
            selector = str(match.group(1)).strip()
            break

    bot_prof_samples: list[dict[str, float | int]] = []
    phases_seen: set[str] = set()
    max_solve_ms = 0.0
    zemdbg_count = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("bot_prof:"):
            prof_match = _BOT_PROF_RE.search(stripped)
            if prof_match:
                bot_prof_samples.append(
                    {
                        "ticks": to_int(prof_match.group("ticks"), 0),
                        "passive": to_float(prof_match.group("passive"), 0.0),
                        "active": to_float(prof_match.group("active"), 0.0),
                        "query": to_float(prof_match.group("query"), 0.0),
                        "update": to_float(prof_match.group("update"), 0.0),
                        "total": to_float(prof_match.group("total"), 0.0),
                    }
                )
        if stripped.startswith("ZEMDBG"):
            zemdbg_count += 1

        phase_match = _PHASE_RE.search(stripped)
        if phase_match:
            phases_seen.add(str(phase_match.group("phase")).strip())

        solve_match = _SOLVE_MS_RE.search(stripped)
        if solve_match:
            max_solve_ms = max(max_solve_ms, to_float(solve_match.group("ms"), 0.0))

    final_results = _parse_final_results(lines)

    max_total = 0.0
    max_update = 0.0
    for sample in bot_prof_samples:
        max_total = max(max_total, to_float(sample.get("total"), 0.0))
        max_update = max(max_update, to_float(sample.get("update"), 0.0))

    return {
        "path": str(path.resolve()),
        "selector": selector or path.stem,
        "state": str(final_results.get("State") or final_results.get("state") or "").strip().lower(),
        "crash_count": max(
            to_int(final_results.get("Crash_count"), 0),
            to_int(final_results.get("crash_count"), 0),
        ),
        "final_results": final_results,
        "bot_prof_samples": len(bot_prof_samples),
        "bot_prof_max_total_ms": max_total,
        "bot_prof_max_update_ms": max_update,
        "bot_profile_p99_total_ms": max(
            to_float(final_results.get("Bot_profile_total_ms_per_tick_p99"), 0.0),
            to_float(final_results.get("bot_profile_total_ms_per_tick_p99"), 0.0),
        ),
        "max_solve_ms": max_solve_ms,
        "phases_seen": sorted(phases_seen),
        "zemdbg_count": zemdbg_count,
    }


def _make_finding(
    *,
    severity: str,
    category: str,
    title: str,
    measured_evidence: dict[str, Any],
    likely_cause: str,
    confidence: str,
    source_refs: list[str],
    selector: str = "",
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "title": title,
        "measured_evidence": measured_evidence,
        "likely_cause": likely_cause,
        "confidence": confidence,
        "source_refs": source_refs,
    }
    selector_token = str(selector).strip()
    if selector_token:
        finding["selector"] = selector_token
    return finding


def _severity_rank(value: str) -> int:
    order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    return order.get(str(value).strip().lower(), 99)


def _confidence_rank(value: str) -> int:
    order = {
        "high": 0,
        "medium": 1,
        "low": 2,
    }
    return order.get(str(value).strip().lower(), 99)


def _append_unique_commands(target: list[str], commands: list[str]) -> None:
    for command in commands:
        token = str(command or "").strip()
        if not token:
            continue
        if token not in target:
            target.append(token)


def _findings_from_compare(
    compare: dict[str, Any],
    *,
    bot: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    repro_bundle: list[str] = []

    global_block = dict(compare.get("global") or {})
    crash_block = dict(global_block.get("crash") or {})
    compute_block = dict(global_block.get("compute") or {})
    summary_delta = dict(global_block.get("summary_delta") or {})

    new_crashes = [row for row in list(crash_block.get("new_crashes") or []) if isinstance(row, dict)]
    candidate_crashes = [
        row for row in list(crash_block.get("candidate_crashes") or []) if isinstance(row, dict)
    ]

    for crash in new_crashes[:3]:
        selector = _selector_from_triplet(
            crash.get("level"),
            crash.get("scenario"),
            crash.get("seed"),
            eval_goal=crash.get("eval_goal"),
        )
        findings.append(
            _make_finding(
                severity="critical",
                category="crash",
                title="New global crash relative to baseline",
                selector=selector,
                measured_evidence={
                    "baseline_state": crash.get("baseline_state"),
                    "candidate_state": crash.get("candidate_state"),
                    "candidate_failure_mode": crash.get("candidate_failure_mode"),
                },
                likely_cause=(
                    "Candidate behavior changed in a globally gated selector and now "
                    "crashes relative to the baseline."
                ),
                confidence="high",
                source_refs=[f"compare:{selector}"],
            )
        )

        repro = dict(crash.get("repro") or {})
        commands = [
            str(repro.get("plot") or "").strip(),
            str(repro.get("sim_trace") or "").strip(),
            str(repro.get("sim_profile") or "").strip(),
        ]
        commands = [cmd for cmd in commands if cmd]
        if commands:
            _append_unique_commands(repro_bundle, commands)
        else:
            _append_unique_commands(
                repro_bundle,
                _repro_commands(selector, bot=bot, include_debug=False),
            )

    notable_compute = bool(compute_block.get("notable_regression", False))
    if notable_compute:
        deltas = dict(compute_block.get("deltas") or {})
        total_p99_delta = dict(deltas.get("bot_profile_total_ms_per_tick_p99") or {})
        total_avg_delta = dict(deltas.get("bot_profile_total_ms_per_tick") or {})
        findings.append(
            _make_finding(
                severity="high",
                category="perf",
                title="Notable global compute regression",
                measured_evidence={
                    "avg_total_delta_ms": total_avg_delta.get("delta_abs"),
                    "p99_total_delta_ms": total_p99_delta.get("delta_abs"),
                    "thresholds": compute_block.get("thresholds"),
                },
                likely_cause=(
                    "Per-tick bot compute increased beyond configured compare thresholds "
                    "for global selectors."
                ),
                confidence="high",
                source_refs=["compare:global.compute"],
            )
        )

    delta_success_rate = to_float(summary_delta.get("success_rate"), 0.0)
    delta_fuel = to_float(summary_delta.get("fuel_mean_primary"), 0.0)
    if delta_success_rate < 0.0:
        findings.append(
            _make_finding(
                severity="medium",
                category="phase",
                title="Global success-rate regression",
                measured_evidence={
                    "delta_success_rate": delta_success_rate,
                    "delta_fuel_mean_primary": delta_fuel,
                },
                likely_cause=(
                    "Control or phase transitions became less stable across global selectors."
                ),
                confidence="medium",
                source_refs=["compare:global.summary_delta"],
            )
        )

    summary = {
        "new_global_crashes": len(new_crashes),
        "candidate_crashes": len(candidate_crashes),
        "notable_global_compute": notable_compute,
    }
    return findings, repro_bundle, summary


def _findings_from_benchmark(
    benchmark: dict[str, Any],
    *,
    bot: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    repro_bundle: list[str] = []

    records = [record for record in list(benchmark.get("records") or []) if isinstance(record, dict)]
    crashed_records = [record for record in records if str(record.get("state") or "") == "crashed"]
    for record in crashed_records[:2]:
        selector = _selector_from_record(record)
        findings.append(
            _make_finding(
                severity="high",
                category="crash",
                title="Crash observed in benchmark records",
                selector=selector,
                measured_evidence={
                    "failure_mode": record.get("failure_mode"),
                    "fuel_consumed": record.get("fuel_consumed"),
                    "time": record.get("time"),
                },
                likely_cause=(
                    "Candidate run reached a failure state for this selector; inspect the per-tick trace."
                ),
                confidence="high",
                source_refs=[f"benchmark:{selector}"],
            )
        )
        _append_unique_commands(
            repro_bundle,
            _repro_commands(selector, bot=bot, include_debug=False),
        )

    scored_phase: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        setup_dx = abs(to_float(record.get("zem_setup_gate_projected_dx"), 0.0))
        terminal_dx = abs(to_float(record.get("zem_terminal_gate_projected_dx"), 0.0))
        score = max(setup_dx, terminal_dx)
        if score <= 50.0:
            continue
        scored_phase.append((score, record))
    scored_phase.sort(key=lambda item: item[0], reverse=True)

    if scored_phase:
        score, record = scored_phase[0]
        selector = _selector_from_record(record)
        findings.append(
            _make_finding(
                severity=("high" if score >= 100.0 else "medium"),
                category="phase",
                title="High projected-dx phase error",
                selector=selector,
                measured_evidence={
                    "zem_setup_gate_projected_dx": record.get("zem_setup_gate_projected_dx"),
                    "zem_terminal_gate_projected_dx": record.get("zem_terminal_gate_projected_dx"),
                },
                likely_cause=(
                    "Setup/coast handoff is leaving excessive lateral correction burden later in flight."
                ),
                confidence="medium",
                source_refs=[f"benchmark:{selector}"],
            )
        )
        _append_unique_commands(
            repro_bundle,
            _repro_commands(selector, bot=bot, include_debug=True),
        )

    scored_perf: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        p99 = max(
            to_float(record.get("bot_profile_total_ms_per_tick_p99"), 0.0),
            to_float(record.get("bot_profile_update_ms_per_tick_p99"), 0.0),
        )
        if p99 <= 20.0:
            continue
        scored_perf.append((p99, record))
    scored_perf.sort(key=lambda item: item[0], reverse=True)

    if scored_perf:
        p99, record = scored_perf[0]
        selector = _selector_from_record(record)
        severity = "high" if p99 >= 50.0 else "medium"
        findings.append(
            _make_finding(
                severity=severity,
                category="perf",
                title="High p99 bot-loop cost in benchmark run",
                selector=selector,
                measured_evidence={
                    "bot_profile_total_ms_per_tick": record.get("bot_profile_total_ms_per_tick"),
                    "bot_profile_total_ms_per_tick_p99": record.get("bot_profile_total_ms_per_tick_p99"),
                    "bot_profile_update_ms_per_tick_p99": record.get("bot_profile_update_ms_per_tick_p99"),
                },
                likely_cause=(
                    "A low-frequency expensive operation is spiking tail latency in the bot loop."
                ),
                confidence="medium",
                source_refs=[f"benchmark:{selector}"],
            )
        )
        _append_unique_commands(
            repro_bundle,
            _repro_commands(selector, bot=bot, include_debug=False),
        )

    return findings, repro_bundle


def _findings_from_sim_logs(
    sim_logs: list[dict[str, Any]],
    *,
    bot: str,
) -> tuple[list[dict[str, Any]], list[str], int]:
    findings: list[dict[str, Any]] = []
    repro_bundle: list[str] = []
    sim_crash_count = 0

    for sim in sim_logs:
        selector = str(sim.get("selector") or "").strip()
        state = str(sim.get("state") or "").strip().lower()
        crash_count = max(0, to_int(sim.get("crash_count"), 0))

        crashed = (crash_count > 0) or (state == "crashed")
        if crashed:
            sim_crash_count += 1
            findings.append(
                _make_finding(
                    severity="critical",
                    category="crash",
                    title="Crash observed in sim log",
                    selector=selector,
                    measured_evidence={
                        "state": state,
                        "crash_count": crash_count,
                        "final_results_path": sim.get("path"),
                    },
                    likely_cause="Run terminated in a crash state for this deterministic selector.",
                    confidence="high",
                    source_refs=[f"sim_log:{sim.get('path')}"],
                )
            )
            _append_unique_commands(
                repro_bundle,
                _repro_commands(selector, bot=bot, include_debug=True),
            )

        p99_total = to_float(sim.get("bot_profile_p99_total_ms"), 0.0)
        max_total = to_float(sim.get("bot_prof_max_total_ms"), 0.0)
        max_update = to_float(sim.get("bot_prof_max_update_ms"), 0.0)
        max_solve = to_float(sim.get("max_solve_ms"), 0.0)

        if p99_total >= 20.0 or max_total >= 20.0 or max_solve >= 100.0:
            severity = "high" if max(p99_total, max_total, max_solve) >= 100.0 else "medium"
            findings.append(
                _make_finding(
                    severity=severity,
                    category="perf",
                    title="Hotspot detected in profiled sim log",
                    selector=selector,
                    measured_evidence={
                        "bot_profile_p99_total_ms": p99_total,
                        "bot_prof_max_total_ms": max_total,
                        "bot_prof_max_update_ms": max_update,
                        "max_solve_ms": max_solve,
                    },
                    likely_cause=(
                        "Profiler output shows a heavy tail or expensive solve path in the control loop."
                    ),
                    confidence="medium",
                    source_refs=[f"sim_log:{sim.get('path')}"],
                )
            )
            _append_unique_commands(
                repro_bundle,
                _repro_commands(selector, bot=bot, include_debug=False),
            )

        phases_seen = [str(phase).strip() for phase in list(sim.get("phases_seen") or []) if str(phase).strip()]
        if phases_seen and max_solve >= 100.0:
            findings.append(
                _make_finding(
                    severity="medium",
                    category="phase",
                    title="Phase transition shows high solver cost",
                    selector=selector,
                    measured_evidence={
                        "phases_seen": phases_seen,
                        "max_solve_ms": max_solve,
                        "zemdbg_count": to_int(sim.get("zemdbg_count"), 0),
                    },
                    likely_cause=(
                        "Phase switching likely triggered a computationally expensive terminal solve."
                    ),
                    confidence="low",
                    source_refs=[f"sim_log:{sim.get('path')}"],
                )
            )

    return findings, repro_bundle, sim_crash_count


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        category = str(finding.get("category") or "").strip()
        title = str(finding.get("title") or "").strip()
        selector = str(finding.get("selector") or "").strip()
        key = (category, title, selector)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _probe_request(
    *,
    findings: list[dict[str, Any]],
    has_compare: bool,
    sim_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    questions: list[str] = []

    if not findings:
        questions.append(
            "No clear anomaly was extracted; add focused counters around setup/terminal control decisions."
        )

    has_perf = any(str(item.get("category") or "") == "perf" for item in findings)
    has_crash = any(str(item.get("category") or "") == "crash" for item in findings)
    has_phase = any(str(item.get("category") or "") == "phase" for item in findings)
    low_confidence = any(str(item.get("confidence") or "") == "low" for item in findings)

    if has_perf and not has_compare:
        questions.append(
            "Collect a baseline-vs-candidate compare report to confirm whether the hotspot is a regression."
        )

    if has_crash and not sim_logs:
        questions.append(
            "Capture `sim --freq 1` logs for the failing selector to locate the first unstable control phase."
        )

    if has_phase:
        zemdbg_lines = sum(to_int(sim.get("zemdbg_count"), 0) for sim in sim_logs)
        if zemdbg_lines <= 0:
            questions.append(
                "Enable `PYLANDER_ZEM_DEBUG_SETUP=1` on the failing selector to inspect setup gate transitions."
            )

    if low_confidence:
        questions.append(
            "Add a focused probe for solver invocation context (phase, projected dx, and fallback reason)."
        )

    deduped: list[str] = []
    for question in questions:
        token = str(question).strip()
        if token and token not in deduped:
            deduped.append(token)

    return {
        "needed": bool(deduped),
        "questions": deduped,
    }


def _doctor_verdict(findings: list[dict[str, Any]]) -> str:
    if any(str(item.get("severity") or "") == "critical" for item in findings):
        return "critical"
    if any(str(item.get("severity") or "") == "high" for item in findings):
        return "investigate"
    if any(str(item.get("severity") or "") == "medium" for item in findings):
        return "watch"
    return "healthy"


def analyze_telemetry(
    *,
    benchmark_payload: dict[str, Any] | None,
    compare_payload: dict[str, Any] | None,
    sim_logs: list[dict[str, Any]],
    source_paths: dict[str, Any],
    bot: str,
    max_findings: int,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    repro_bundle: list[str] = []

    summary_new_global_crashes = 0
    summary_candidate_crashes = 0
    summary_notable_global_compute = False

    if compare_payload is not None:
        compare_findings, compare_repro, compare_summary = _findings_from_compare(
            compare_payload,
            bot=bot,
        )
        findings.extend(compare_findings)
        _append_unique_commands(repro_bundle, compare_repro)
        summary_new_global_crashes = to_int(compare_summary.get("new_global_crashes"), 0)
        summary_candidate_crashes = to_int(compare_summary.get("candidate_crashes"), 0)
        summary_notable_global_compute = bool(compare_summary.get("notable_global_compute", False))

    if benchmark_payload is not None:
        bench_findings, bench_repro = _findings_from_benchmark(
            benchmark_payload,
            bot=bot,
        )
        findings.extend(bench_findings)
        _append_unique_commands(repro_bundle, bench_repro)

    sim_findings, sim_repro, sim_log_crashes = _findings_from_sim_logs(
        sim_logs,
        bot=bot,
    )
    findings.extend(sim_findings)
    _append_unique_commands(repro_bundle, sim_repro)

    deduped = _dedupe_findings(findings)
    sorted_findings = sorted(
        deduped,
        key=lambda item: (
            _severity_rank(str(item.get("severity") or "")),
            _confidence_rank(str(item.get("confidence") or "")),
            str(item.get("title") or ""),
            str(item.get("selector") or ""),
        ),
    )
    trimmed = sorted_findings[: max(1, int(max_findings))]

    probe_request = _probe_request(
        findings=trimmed,
        has_compare=compare_payload is not None,
        sim_logs=sim_logs,
    )

    next_actions: list[str] = []
    if trimmed:
        next_actions.append("Run the top repro command bundle and capture deterministic outputs.")
    if probe_request["needed"]:
        next_actions.append(
            "Generate a focused probe plan with pylander-telemetry-builder using this triage report."
        )
    if compare_payload is None:
        next_actions.append(
            "Run a baseline compare benchmark for regression-grade interpretation of perf signals."
        )

    report = {
        "contract": "telemetry_triage_report.v1",
        "doctor_verdict": _doctor_verdict(trimmed),
        "sources": {
            "benchmark_json": str(source_paths.get("benchmark_json") or ""),
            "compare_json": str(source_paths.get("compare_json") or ""),
            "sim_logs": [
                str(path) for path in list(source_paths.get("sim_logs") or []) if str(path).strip()
            ],
        },
        "summary": {
            "new_global_crashes": summary_new_global_crashes,
            "candidate_crashes": summary_candidate_crashes,
            "sim_log_crashes": max(0, int(sim_log_crashes)),
            "notable_global_compute": summary_notable_global_compute,
            "total_findings": len(trimmed),
        },
        "top_findings": trimmed,
        "repro_bundle": repro_bundle,
        "probe_request": probe_request,
        "next_actions": next_actions,
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(report, "telemetry_triage_report.v1")
    return report


def _default_output_path() -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "")
    return (_REPO_ROOT / "outputs" / "diagnostics" / f"telemetry_{stamp}.json").resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Pylander telemetry artifacts and logs")
    parser.add_argument("--benchmark-json", default=None)
    parser.add_argument("--compare-json", default=None)
    parser.add_argument("--sim-log", action="append", default=[])
    parser.add_argument("--bot", default="zem_zev")
    parser.add_argument("--max-findings", type=int, default=8)
    parser.add_argument("--output-report", default=None)
    args = parser.parse_args()

    benchmark_path = str(args.benchmark_json or "").strip()
    compare_path = str(args.compare_json or "").strip()
    sim_paths = [str(path).strip() for path in list(args.sim_log or []) if str(path).strip()]

    if not benchmark_path and not compare_path and not sim_paths:
        raise SystemExit(
            "At least one input is required: --benchmark-json, --compare-json, or --sim-log"
        )

    benchmark_payload = load_json(benchmark_path) if benchmark_path else None
    compare_payload = load_json(compare_path) if compare_path else None

    parsed_logs = [_parse_sim_log(Path(path)) for path in sim_paths]

    report = analyze_telemetry(
        benchmark_payload=benchmark_payload,
        compare_payload=compare_payload,
        sim_logs=parsed_logs,
        source_paths={
            "benchmark_json": str(Path(benchmark_path).resolve()) if benchmark_path else "",
            "compare_json": str(Path(compare_path).resolve()) if compare_path else "",
            "sim_logs": [str(Path(path).resolve()) for path in sim_paths],
        },
        bot=str(args.bot),
        max_findings=max(1, int(args.max_findings)),
    )

    output_path = Path(args.output_report).resolve() if args.output_report else _default_output_path()
    out_path = write_json(output_path, report)
    print(f"# telemetry_report\njson={out_path}")


if __name__ == "__main__":
    main()
