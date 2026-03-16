from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(rel: str) -> Path:
    return (REPO_ROOT / rel).resolve()


builder = _load_module(
    "telemetry_builder_script",
    _script("skills/pylander-telemetry-builder/scripts/plan_telemetry.py"),
)
contracts = _load_module(
    "skill_contracts_for_builder", _script("skills/lib/contracts.py")
)


def _triage_payload() -> dict[str, object]:
    return {
        "contract": "telemetry_triage_report.v1",
        "doctor_verdict": "investigate",
        "sources": {
            "benchmark_json": "/tmp/bench.json",
            "compare_json": "/tmp/compare.json",
            "sim_logs": ["/tmp/sim.log"],
        },
        "summary": {
            "new_global_crashes": 0,
            "candidate_crashes": 0,
            "sim_log_crashes": 0,
            "notable_global_compute": True,
            "total_findings": 1,
        },
        "top_findings": [
            {
                "severity": "high",
                "category": "perf",
                "title": "Notable global compute regression",
                "selector": "setup_flat:far_half:0",
                "measured_evidence": {"p99_total_delta_ms": 2.5},
                "likely_cause": "Tail latency spike",
                "confidence": "high",
                "source_refs": ["compare:global.compute"],
            }
        ],
        "repro_bundle": [
            "uv run python main.py sim setup_flat:far_half:0 --bot pdg --freq 1",
        ],
        "probe_request": {
            "needed": True,
            "questions": ["Need focused hotspot probes"],
        },
        "next_actions": ["Run focused repro"],
        "created_at_utc": "2026-03-04T00:00:00+00:00",
    }


def test_build_probe_plan_emits_valid_contract(tmp_path: Path) -> None:
    triage = _triage_payload()
    triage_path = tmp_path / "triage.json"
    triage_path.write_text("{}", encoding="utf-8")

    plan = builder.build_probe_plan(
        triage,
        triage_report_path=str(triage_path),
        scope=["runtime", "pdg"],
        overhead_budget_avg_ms=0.05,
        overhead_budget_p99_ms=0.20,
    )

    contracts.validate_contract_data(plan, "telemetry_probe_plan.v1")
    assert plan["target_issue"].startswith("Notable global compute regression")
    assert len(plan["probe_set"]) >= 1

    for probe in plan["probe_set"]:
        assert probe["file_target"]
        assert probe["insertion_anchor"]
        assert probe["sampling_or_gate"]["env_var"]


def test_build_probe_plan_fallback_when_no_findings(tmp_path: Path) -> None:
    triage = _triage_payload()
    triage["top_findings"] = []
    triage["summary"] = {
        "new_global_crashes": 0,
        "candidate_crashes": 0,
        "sim_log_crashes": 0,
        "notable_global_compute": False,
        "total_findings": 0,
    }

    triage_path = tmp_path / "triage_empty.json"
    triage_path.write_text("{}", encoding="utf-8")

    plan = builder.build_probe_plan(
        triage,
        triage_report_path=str(triage_path),
        scope=[],
        overhead_budget_avg_ms=0.05,
        overhead_budget_p99_ms=0.20,
    )

    contracts.validate_contract_data(plan, "telemetry_probe_plan.v1")
    assert plan["target_issue"] == "insufficient_signal"
    assert len(plan["probe_set"]) == 1
