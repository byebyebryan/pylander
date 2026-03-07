from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


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


contracts = _load_module("skill_contracts", _script("skills/lib/contracts.py"))
route_mod = _load_module(
    "route_tuning_script", _script("skills/pylander-tune-routing-planner/scripts/route_tuning.py")
)
strategy_arena_mod = _load_module(
    "strategy_arena_script",
    _script("skills/pylander-strategy-orchestrator/scripts/run_strategy_arena.py"),
)
tune_loop_mod = _load_module(
    "tune_loop_script", _script("skills/pylander-tune-loop-manager/scripts/run_tune_loop.py")
)
regression_mod = _load_module(
    "regression_gate_script",
    _script("skills/pylander-regression-analyzer/scripts/gate_regression.py"),
)


def test_contract_validation_rejects_missing_required() -> None:
    bad_payload = {
        "contract": "route_decision.v1",
        "recommended_route": "arena",
    }
    with pytest.raises(contracts.ContractValidationError):
        contracts.validate_contract_data(bad_payload, "route_decision.v1")


def test_route_auto_selects_arena_on_conflict() -> None:
    payload = {
        "strategy_winner_ref": "branch_a",
        "focused_selectors": ["setup_flat:mid:0", "flare_error:mid_wide:0"],
        "baseline_ref": "main",
        "tuning_route": "auto",
        "recent_metrics": {
            "candidate_directions": 3,
            "viable_directions": 2,
            "loop_plateau_iterations": 3,
            "last_fuel_mean_primary_delta": -0.35,
            "compute_avg_total_delta_ms": 0.18,
            "compute_p99_total_delta_ms": 0.40,
            "selector_success_rate_stddev": 0.06,
            "selector_fuel_cv": 0.20,
        },
    }
    out = route_mod.route_tuning(payload)
    assert out["recommended_route"] == "arena"
    assert out["handoff_payload"]["target_skill"] == "pylander-tune-orchestrator"


def test_route_manual_override_loop() -> None:
    payload = {
        "strategy_winner_ref": "branch_b",
        "focused_selectors": ["setup_flat:mid:0"],
        "tuning_route": "loop",
    }
    out = route_mod.route_tuning(payload)
    assert out["recommended_route"] == "loop"
    assert out["confidence"] == "high"


def test_strategy_arena_selects_top_passing_branch() -> None:
    payload = {
        "arena_id": "arena_demo",
        "focused_selectors": ["setup_flat:mid:0"],
        "branches": [
            {
                "inline_report": {
                    "contract": "arena_branch_report.v1",
                    "arena_id": "arena_demo",
                    "arena_type": "strategy",
                    "branch_id": "good",
                    "decision": "promote",
                    "summary": {
                        "success_rate": 1.0,
                        "success_rate_delta": 0.10,
                        "fuel_mean_primary_delta": -0.60,
                        "new_global_crashes": 0,
                        "compute_avg_total_delta_ms": 0.02,
                        "compute_p99_total_delta_ms": 0.05,
                        "observation_regressions": 0,
                        "notable_global_regression": False,
                    },
                    "top_repros": [],
                    "commands": [],
                    "notes": "good",
                    "created_at_utc": "2026-03-04T00:00:00+00:00",
                }
            },
            {
                "inline_report": {
                    "contract": "arena_branch_report.v1",
                    "arena_id": "arena_demo",
                    "arena_type": "strategy",
                    "branch_id": "bad",
                    "decision": "drop",
                    "summary": {
                        "success_rate": 0.5,
                        "success_rate_delta": -0.20,
                        "fuel_mean_primary_delta": 0.10,
                        "new_global_crashes": 1,
                        "compute_avg_total_delta_ms": 0.30,
                        "compute_p99_total_delta_ms": 0.50,
                        "observation_regressions": 1,
                        "notable_global_regression": True,
                    },
                    "top_repros": [],
                    "commands": [],
                    "notes": "bad",
                    "created_at_utc": "2026-03-04T00:00:00+00:00",
                }
            },
        ],
    }
    out = strategy_arena_mod.run_strategy_arena(payload, execute_workers=False)
    assert out["outcome"] == "winner"
    assert out["winner_branch_id"] == "good"
    assert out["next_step_handoff"]["target_skill"] == "pylander-tune-routing-planner"


def test_tune_loop_marks_hard_blocker() -> None:
    payload = {
        "selector_scope": ["setup_flat:mid:0"],
        "profile": "light",
        "min_success_rate": 0.8,
        "iterations": [
            {
                "success_rate": 0.7,
                "success_rate_delta": -0.2,
                "fuel_mean_primary_delta": -0.3,
                "new_global_crashes": 0,
                "compute_avg_total_delta_ms": 0.05,
                "compute_p99_total_delta_ms": 0.10,
            }
        ],
    }
    out = tune_loop_mod.run_tune_loop(payload)
    assert out["iterations"][0]["decision"] == "abort"
    assert out["final_decision"] == "hard_blocker"


def test_regression_gate_uses_compare_report(tmp_path: Path) -> None:
    compare = {
        "global": {
            "notable_regression": True,
            "summary_delta": {"success_rate": -0.01},
            "crash": {"new_crashes": []},
            "compute": {"notable_regression": True},
            "worst_scenarios": [{"scenario": "setup_flat:mid"}],
        }
    }
    compare_path = tmp_path / "compare.json"
    compare_path.write_text(json.dumps(compare), encoding="utf-8")

    payload = {
        "mode": "quick",
        "baseline_ref": "main",
        "compare_report_path": str(compare_path),
    }
    out = regression_mod.gate_regression(payload, execute=False)
    assert out["gate_verdict"] == "investigate"
    assert out["evidence"]["notable_global_compute"] is True


def test_cli_dry_run_smoke(tmp_path: Path) -> None:
    route_input = tmp_path / "route_input.json"
    route_output = tmp_path / "route_output.json"
    route_input.write_text(
        json.dumps(
            {
                "strategy_winner_ref": "demo",
                "focused_selectors": ["setup_flat:mid:0"],
                "tuning_route": "auto",
                "recent_metrics": {"candidate_directions": 1, "viable_directions": 1},
            }
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_script("skills/pylander-tune-routing-planner/scripts/route_tuning.py")),
        "--input",
        str(route_input),
        "--output",
        str(route_output),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert route_output.exists()

    worker_input = tmp_path / "worker_input.json"
    worker_output = tmp_path / "worker_output.json"
    worker_input.write_text(
        json.dumps(
            {
                "arena_id": "arena_smoke",
                "arena_type": "strategy",
                "branch_id": "branch_1",
                "selectors": ["setup_flat:mid:0"],
                "measured_metrics": {
                    "success_rate": 1.0,
                    "success_rate_delta": 0.05,
                    "fuel_mean_primary_delta": -0.2,
                    "new_global_crashes": 0,
                    "compute_avg_total_delta_ms": 0.01,
                    "compute_p99_total_delta_ms": 0.05,
                },
            }
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_script("skills/pylander-arena-branch-runner/scripts/run_arena_branch.py")),
        "--input",
        str(worker_input),
        "--output",
        str(worker_output),
        "--no-execute-validation",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert worker_output.exists()

    strategy_input = tmp_path / "strategy_input.json"
    strategy_output = tmp_path / "strategy_output.json"
    strategy_input.write_text(
        json.dumps(
            {
                "arena_id": "arena_smoke",
                "focused_selectors": ["setup_flat:mid:0"],
                "branches": [{"report_path": str(worker_output)}],
            }
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_script("skills/pylander-strategy-orchestrator/scripts/run_strategy_arena.py")),
        "--input",
        str(strategy_input),
        "--output",
        str(strategy_output),
        "--no-execute-workers",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert strategy_output.exists()

    tune_input = tmp_path / "tune_input.json"
    tune_output = tmp_path / "tune_output.json"
    tune_input.write_text(
        json.dumps(
            {
                "selector_scope": ["setup_flat:mid:0"],
                "profile": "light",
                "iterations": [],
            }
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_script("skills/pylander-tune-loop-manager/scripts/run_tune_loop.py")),
        "--input",
        str(tune_input),
        "--output",
        str(tune_output),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert tune_output.exists()

    compare_path = tmp_path / "compare_for_cli.json"
    compare_path.write_text(
        json.dumps(
            {
                "global": {
                    "notable_regression": False,
                    "summary_delta": {"success_rate": 0.01},
                    "crash": {"new_crashes": []},
                    "compute": {"notable_regression": False},
                    "worst_scenarios": [],
                }
            }
        ),
        encoding="utf-8",
    )
    reg_input = tmp_path / "reg_input.json"
    reg_output = tmp_path / "reg_output.json"
    reg_input.write_text(
        json.dumps(
            {
                "mode": "quick",
                "baseline_ref": "main",
                "compare_report_path": str(compare_path),
            }
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_script("skills/pylander-regression-analyzer/scripts/gate_regression.py")),
        "--input",
        str(reg_input),
        "--output",
        str(reg_output),
        "--no-execute",
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert reg_output.exists()

    doctor_compare = tmp_path / "doctor_compare.json"
    doctor_compare.write_text(
        json.dumps(
            {
                "global": {
                    "summary_delta": {"success_rate": -0.01},
                    "crash": {
                        "new_crashes": [
                            {
                                "level": "launch",
                                "scenario": "mid",
                                "seed": 0,
                                "baseline_state": "landed",
                                "candidate_state": "crashed",
                                "candidate_failure_mode": "impact",
                                "repro": {
                                    "plot": "uv run python main.py plot setup_flat:mid:0 --bot zem_zev",
                                    "sim_trace": (
                                        "uv run python main.py sim setup_flat:mid:0 --bot zem_zev --freq 1"
                                    ),
                                    "sim_profile": (
                                        "PYLANDER_BOT_PROFILE=1 uv run python main.py sim setup_flat:mid:0 "
                                        "--bot zem_zev --freq 1"
                                    ),
                                },
                            }
                        ],
                        "candidate_crashes": [],
                    },
                    "compute": {"notable_regression": False},
                }
            }
        ),
        encoding="utf-8",
    )
    doctor_output = tmp_path / "telemetry_report.json"
    cmd = [
        sys.executable,
        str(_script("skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py")),
        "--compare-json",
        str(doctor_compare),
        "--output-report",
        str(doctor_output),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert doctor_output.exists()
    telemetry_report = json.loads(doctor_output.read_text(encoding="utf-8"))
    contracts.validate_contract_data(telemetry_report, "telemetry_triage_report.v1")

    builder_output = tmp_path / "telemetry_probe_plan.json"
    cmd = [
        sys.executable,
        str(_script("skills/pylander-telemetry-builder/scripts/plan_telemetry.py")),
        "--triage-report",
        str(doctor_output),
        "--output-plan",
        str(builder_output),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout
    assert builder_output.exists()
    telemetry_plan = json.loads(builder_output.read_text(encoding="utf-8"))
    contracts.validate_contract_data(telemetry_plan, "telemetry_probe_plan.v1")
