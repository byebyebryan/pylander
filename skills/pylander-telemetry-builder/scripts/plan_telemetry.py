from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import load_json, to_float, utc_now_iso, write_json  # noqa: E402


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


def _normalize_scope(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        if token not in out:
            out.append(token)
    return out


def _select_target_issue(triage: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    findings = [
        row for row in list(triage.get("top_findings") or []) if isinstance(row, dict)
    ]
    findings.sort(
        key=lambda row: (
            _severity_rank(str(row.get("severity") or "")),
            _confidence_rank(str(row.get("confidence") or "")),
            str(row.get("title") or ""),
        )
    )
    if not findings:
        return "insufficient_signal", []

    top = findings[0]
    selector = str(top.get("selector") or "").strip()
    selector_suffix = f" ({selector})" if selector else ""
    return (
        f"{str(top.get('title') or 'top_finding').strip()}{selector_suffix}",
        findings,
    )


def _probe_template(
    *,
    idx: int,
    category: str,
    avg_budget: float,
    p99_budget: float,
) -> dict[str, Any]:
    category_token = str(category or "").strip().lower()

    if category_token == "crash":
        return {
            "probe_id": f"probe_{idx:02d}_crash_trace",
            "kind": "event_log",
            "file_target": "app/run_single.py",
            "insertion_anchor": "headless run loop termination branch",
            "schema": {
                "event": "crash_transition",
                "fields": [
                    "selector",
                    "time",
                    "state",
                    "failure_mode",
                    "phase",
                    "vx",
                    "vy",
                    "fuel",
                ],
            },
            "sampling_or_gate": {
                "env_var": "PYLANDER_TELEM_CRASH_TRACE",
                "mode": "event_only",
                "sample_rate": 1.0,
            },
            "expected_signal": "Single deterministic crash transition payload per failing run.",
            "risk_and_overhead": {
                "expected_avg_overhead_ms": max(0.0, avg_budget * 0.20),
                "expected_p99_overhead_ms": max(0.0, p99_budget * 0.40),
                "risk_level": "low",
            },
            "expiry_condition": "Remove after crash root cause is fixed and covered by regression test.",
        }

    if category_token == "phase":
        return {
            "probe_id": f"probe_{idx:02d}_phase_handoff",
            "kind": "metric",
            "file_target": "bots/pdg/__init__.py",
            "insertion_anchor": "phase transition and projected-dx handoff points",
            "schema": {
                "metric": "phase_handoff_dx",
                "fields": [
                    "phase",
                    "projected_dx",
                    "target_dx",
                    "gate_state",
                    "solve_ms",
                ],
            },
            "sampling_or_gate": {
                "env_var": "PYLANDER_TELEM_PHASE_TRACE",
                "mode": "phase_transition",
                "sample_rate": 1.0,
            },
            "expected_signal": "Projected-dx drift captured at setup/coast/flare handoff boundaries.",
            "risk_and_overhead": {
                "expected_avg_overhead_ms": max(0.0, avg_budget * 0.30),
                "expected_p99_overhead_ms": max(0.0, p99_budget * 0.50),
                "risk_level": "medium",
            },
            "expiry_condition": "Remove after handoff stability metric is within expected range for 2 compare runs.",
        }

    if category_token == "debug":
        return {
            "probe_id": f"probe_{idx:02d}_debug_counter",
            "kind": "counter",
            "file_target": "bots/pdg/__init__.py",
            "insertion_anchor": "debug setup trace emission point",
            "schema": {
                "metric": "setup_debug_event_count",
                "fields": ["selector", "phase", "event_type"],
            },
            "sampling_or_gate": {
                "env_var": "PYLANDER_TELEM_DEBUG_COUNTER",
                "mode": "sampled",
                "sample_rate": 0.2,
            },
            "expected_signal": "Event-rate comparison across failing vs passing selectors.",
            "risk_and_overhead": {
                "expected_avg_overhead_ms": max(0.0, avg_budget * 0.10),
                "expected_p99_overhead_ms": max(0.0, p99_budget * 0.20),
                "risk_level": "low",
            },
            "expiry_condition": "Remove after anomaly attribution is confirmed.",
        }

    return {
        "probe_id": f"probe_{idx:02d}_perf_hotspot",
        "kind": "histogram",
        "file_target": "runtime/metrics.py",
        "insertion_anchor": "BotLoopProfiler update path for actor timings",
        "schema": {
            "metric": "bot_loop_hotspot",
            "fields": ["selector", "phase", "passive_ms", "update_ms", "total_ms"],
        },
        "sampling_or_gate": {
            "env_var": "PYLANDER_TELEM_PERF_TRACE",
            "mode": "sampled_ticks",
            "sample_rate": 0.1,
        },
        "expected_signal": "Tail spikes localized to passive or update segment with phase context.",
        "risk_and_overhead": {
            "expected_avg_overhead_ms": max(0.0, avg_budget * 0.35),
            "expected_p99_overhead_ms": max(0.0, p99_budget * 0.60),
            "risk_level": "medium",
        },
        "expiry_condition": "Remove after p99 regression is either fixed or accepted with documented tradeoff.",
    }


def _validation_commands(
    triage: dict[str, Any],
    *,
    primary_env_flag: str,
) -> list[str]:
    commands: list[str] = []

    for command in list(triage.get("repro_bundle") or [])[:3]:
        token = str(command).strip()
        if token and token not in commands:
            commands.append(token)

    if not commands:
        commands.extend(
            [
                "uv run python main.py sim setup_flat:near_half:0 --bot pdg --freq 1",
                "PYLANDER_BOT_PROFILE=1 uv run python main.py sim setup_flat:near_half:0 --bot pdg --freq 1",
            ]
        )

    if primary_env_flag:
        commands.append(
            f"{primary_env_flag}=1 uv run python main.py sim setup_flat:near_half:0 --bot pdg --freq 1"
        )

    return commands


def build_probe_plan(
    triage_report: dict[str, Any],
    *,
    triage_report_path: str,
    scope: list[str],
    overhead_budget_avg_ms: float,
    overhead_budget_p99_ms: float,
) -> dict[str, Any]:
    validate_contract_data(triage_report, "telemetry_triage_report.v1")

    target_issue, findings = _select_target_issue(triage_report)
    selected = findings[:3] if findings else []

    probe_set: list[dict[str, Any]] = []
    for idx, finding in enumerate(selected, start=1):
        category = str(finding.get("category") or "perf").strip().lower() or "perf"
        probe_set.append(
            _probe_template(
                idx=idx,
                category=category,
                avg_budget=overhead_budget_avg_ms,
                p99_budget=overhead_budget_p99_ms,
            )
        )

    if not probe_set:
        probe_set.append(
            _probe_template(
                idx=1,
                category="perf",
                avg_budget=overhead_budget_avg_ms,
                p99_budget=overhead_budget_p99_ms,
            )
        )

    first_flag = str(
        probe_set[0].get("sampling_or_gate", {}).get("env_var") or ""
    ).strip()

    payload = {
        "contract": "telemetry_probe_plan.v1",
        "input_triage_report_path": str(Path(triage_report_path).resolve()),
        "target_issue": target_issue,
        "scope": _normalize_scope(scope),
        "probe_set": probe_set,
        "validation_commands": _validation_commands(
            triage_report,
            primary_env_flag=first_flag,
        ),
        "rollout_and_cleanup": {
            "enable_flag": first_flag,
            "disable_flag": f"{first_flag}=0" if first_flag else "disabled",
            "expiry_condition": "Delete probes after issue confirmation and regression coverage.",
            "cleanup_steps": [
                "Remove temporary probe fields and emitters from target files.",
                "Remove probe env flag handling from runtime docs if added.",
                "Keep only durable metrics that are used by benchmark reports.",
            ],
        },
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(payload, "telemetry_probe_plan.v1")
    return payload


def _default_output_path() -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "")
    return (
        _REPO_ROOT / "outputs" / "diagnostics" / f"telemetry_probe_plan_{stamp}.json"
    ).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build focused Pylander telemetry probe plans"
    )
    parser.add_argument("--triage-report", required=True)
    parser.add_argument("--scope", nargs="*", default=[])
    parser.add_argument("--overhead-budget-avg-ms", type=float, default=0.05)
    parser.add_argument("--overhead-budget-p99-ms", type=float, default=0.20)
    parser.add_argument("--output-plan", default=None)
    args = parser.parse_args()

    triage_path = str(args.triage_report)
    triage_report = load_json(triage_path)

    payload = build_probe_plan(
        triage_report,
        triage_report_path=triage_path,
        scope=[str(item) for item in list(args.scope or [])],
        overhead_budget_avg_ms=max(0.0, to_float(args.overhead_budget_avg_ms, 0.05)),
        overhead_budget_p99_ms=max(0.0, to_float(args.overhead_budget_p99_ms, 0.20)),
    )

    output_path = (
        Path(args.output_plan).resolve() if args.output_plan else _default_output_path()
    )
    out_path = write_json(output_path, payload)
    print(f"# telemetry_probe_plan\njson={out_path}")


if __name__ == "__main__":
    main()
