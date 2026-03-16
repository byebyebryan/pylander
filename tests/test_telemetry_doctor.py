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


doctor = _load_module(
    "telemetry_doctor_script",
    _script("skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py"),
)
contracts = _load_module(
    "skill_contracts_for_doctor", _script("skills/lib/contracts.py")
)


def test_parse_sim_log_extracts_final_results_and_profile(tmp_path: Path) -> None:
    log_path = tmp_path / "sim.log"
    log_path.write_text(
        "\n".join(
            [
                "Mode: headless run",
                "Selector: boost_flat:near_half:0",
                "bot_prof: ticks=16 passive=0.012ms/t update=10.364ms/t total=10.387ms/t",
                "t=  0.02 | ship x=-0.0 alt=0.0 vx=-0.00 vy=0.00 ang=0.0 thr=0% fuel=100.0% | bot=pdg mode=opt phase=boost dx=214.5 pdx=214.5 slv:177.0ms",
                "",
                "============================================================",
                "FINAL RESULTS",
                "============================================================",
                "[Run]",
                "state : crashed",
                "",
                "[Outcome]",
                "crash_count : 1",
                "",
                "[Profiler]",
                "bot_profile_total_ms_per_tick_p99 : 134.26",
                "============================================================",
            ]
        ),
        encoding="utf-8",
    )

    parsed = doctor._parse_sim_log(log_path)
    assert parsed["selector"] == "boost_flat:near_half:0"
    assert parsed["state"] == "crashed"
    assert parsed["crash_count"] == 1
    assert parsed["bot_profile_p99_total_ms"] == 134.26
    assert parsed["max_solve_ms"] == 177.0


def test_analyze_compare_produces_crash_and_perf_findings() -> None:
    compare_payload = {
        "global": {
            "summary_delta": {"success_rate": -0.05, "fuel_mean_primary": 1.2},
            "crash": {
                "new_crashes": [
                    {
                        "level": "boost_flat",
                        "scenario": "mid_half",
                        "seed": 2,
                        "baseline_state": "landed",
                        "candidate_state": "crashed",
                        "candidate_failure_mode": "impact",
                        "repro": {
                            "plot": "uv run python main.py plot boost_flat:mid_half:2 --bot pdg",
                            "sim_trace": "uv run python main.py sim boost_flat:mid_half:2 --bot pdg --freq 1",
                            "sim_profile": "PYLANDER_BOT_PROFILE=1 uv run python main.py sim boost_flat:mid_half:2 --bot pdg --freq 1",
                        },
                    }
                ],
                "candidate_crashes": [
                    {"level": "boost_flat", "scenario": "mid_half", "seed": 2}
                ],
            },
            "compute": {
                "notable_regression": True,
                "deltas": {
                    "bot_profile_total_ms_per_tick": {"delta_abs": 0.3},
                    "bot_profile_total_ms_per_tick_p99": {"delta_abs": 2.5},
                },
                "thresholds": {"p99_total": {"abs_min_ms": 0.2}},
            },
        }
    }

    report = doctor.analyze_telemetry(
        benchmark_payload=None,
        compare_payload=compare_payload,
        sim_logs=[],
        source_paths={
            "benchmark_json": "",
            "compare_json": "/tmp/compare.json",
            "sim_logs": [],
        },
        bot="pdg",
        max_findings=8,
    )

    assert report["doctor_verdict"] == "critical"
    assert report["summary"]["new_global_crashes"] == 1
    assert report["summary"]["notable_global_compute"] is True
    assert any(item["category"] == "perf" for item in report["top_findings"])
    assert any("boost_flat:mid_half:2" in cmd for cmd in report["repro_bundle"])
    contracts.validate_contract_data(report, "telemetry_triage_report.v1")


def test_analyze_benchmark_without_compare_requests_probe() -> None:
    benchmark_payload = {
        "records": [
            {
                "level": "boost_flat",
                "scenario": "far_half",
                "seed": 0,
                "state": "landed",
                "boost_cutoff_projected_dx": 140.0,
                "bot_test_bot_terminal_entry_projected_dx": 82.0,
                "bot_profile_total_ms_per_tick": 1.4,
                "bot_profile_total_ms_per_tick_p99": 62.0,
                "bot_profile_update_ms_per_tick_p99": 55.0,
            }
        ]
    }

    report = doctor.analyze_telemetry(
        benchmark_payload=benchmark_payload,
        compare_payload=None,
        sim_logs=[],
        source_paths={
            "benchmark_json": "/tmp/bench.json",
            "compare_json": "",
            "sim_logs": [],
        },
        bot="test-bot",
        max_findings=8,
    )

    assert report["doctor_verdict"] in {"investigate", "watch"}
    assert report["probe_request"]["needed"] is True
    assert any(
        "baseline-vs-candidate" in q for q in report["probe_request"]["questions"]
    )
    phase_findings = [
        item for item in report["top_findings"] if item["category"] == "phase"
    ]
    assert phase_findings
    assert (
        phase_findings[0]["measured_evidence"]["bot_terminal_entry_projected_dx"] == 82.0
    )
    assert (
        phase_findings[0]["measured_evidence"]["bot_terminal_entry_projected_dx_field"]
        == "bot_test_bot_terminal_entry_projected_dx"
    )
    contracts.validate_contract_data(report, "telemetry_triage_report.v1")
