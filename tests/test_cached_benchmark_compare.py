from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pylander-benchmark-runner"
    / "scripts"
)
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import run_cached_benchmark as cached_bench  # noqa: E402


def _record(
    *,
    level: str,
    scenario: str,
    seed: int,
    state: str,
    success: bool,
    fuel: float,
) -> dict[str, object]:
    return {
        "level": level,
        "scenario": scenario,
        "seed": seed,
        "state": state,
        "success": success,
        "failure_mode": "none" if success else state,
        "fuel_consumed": fuel,
        "fuel_per_distance": fuel / 100.0,
        "time": 10.0,
    }


def _with_profile(record: dict[str, object], **overrides: float) -> dict[str, object]:
    out = dict(record)
    out.update(
        {
            "bot_profile_ticks": 600.0,
            "bot_profile_total_ms_per_tick": 0.50,
            "bot_profile_passive_ms_per_tick": 0.10,
            "bot_profile_update_ms_per_tick": 0.10,
            "bot_profile_total_ms_per_tick_p90": 0.60,
            "bot_profile_total_ms_per_tick_p99": 0.70,
            "bot_profile_update_ms_per_tick_p90": 0.14,
            "bot_profile_update_ms_per_tick_p99": 0.20,
        }
    )
    out.update(overrides)
    return out


def test_observation_only_crash_does_not_mark_notable_regression() -> None:
    baseline = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            _record(level="setup_climb", scenario="mid", seed=0, state="landed", success=True, fuel=30.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=21.0),
            _record(level="setup_climb", scenario="mid", seed=0, state="crashed", success=False, fuel=31.0),
        ]
    }
    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"setup_flat": "normal", "setup_climb": "observe_only"},
        bot="zem_zev",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is False
    assert len(report["global"]["crash"]["new_crashes"]) == 0
    assert len(report["observation"]["crash"]["new_crashes"]) == 1


def test_normal_crash_marks_notable_regression() -> None:
    baseline = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="crashed", success=False, fuel=22.0),
        ]
    }
    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"setup_flat": "normal"},
        bot="zem_zev",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert len(report["global"]["crash"]["new_crashes"]) == 1


def test_scenario_regressions_group_by_level_and_scenario() -> None:
    baseline = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            _record(level="flare_error", scenario="mid", seed=0, state="landed", success=True, fuel=40.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=25.0),
            _record(level="flare_error", scenario="mid", seed=0, state="landed", success=True, fuel=35.0),
        ]
    }

    rows = cached_bench._scenario_regressions(baseline, candidate)
    names = {str(item["scenario"]) for item in rows}
    assert names == {"setup_flat:mid", "flare_error:mid"}


def test_scenario_regressions_separate_non_landing_goal_by_selector() -> None:
    baseline = {
        "records": [
            {
                **_record(level="setup_downhill", scenario="mid", seed=0, state="flying", success=True, fuel=20.0),
                "eval_goal": "setup",
            }
        ]
    }
    candidate = {
        "records": [
            {
                **_record(level="setup_downhill", scenario="mid", seed=0, state="flying", success=False, fuel=24.0),
                "eval_goal": "setup",
            }
        ]
    }

    rows = cached_bench._scenario_regressions(baseline, candidate)
    assert [str(item["scenario"]) for item in rows] == ["setup_downhill:mid:setup"]


def test_global_compute_regression_marks_notable_regression() -> None:
    baseline = {
        "records": [
            _with_profile(
                _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            )
        ]
    }
    candidate = {
        "records": [
            _with_profile(
                _record(level="setup_flat", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
                bot_profile_total_ms_per_tick=0.75,
                bot_profile_total_ms_per_tick_p99=1.10,
                bot_profile_update_ms_per_tick_p99=0.34,
            )
        ]
    }

    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"setup_flat": "normal"},
        bot="zem_zev",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert report["global"]["compute"]["notable_regression"] is True
    assert report["global"]["compute"]["notable_any"] is True


def test_observation_compute_regression_does_not_gate_global() -> None:
    baseline = {
        "records": [
            _with_profile(
                _record(level="setup_climb", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            )
        ]
    }
    candidate = {
        "records": [
            _with_profile(
                _record(level="setup_climb", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
                bot_profile_total_ms_per_tick=0.78,
                bot_profile_total_ms_per_tick_p99=1.15,
                bot_profile_update_ms_per_tick_p99=0.36,
            )
        ]
    }

    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"setup_climb": "observe_only"},
        bot="zem_zev",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is False
    assert report["global"]["compute"]["available"] is False
    assert report["observation"]["compute"]["notable_regression"] is True


def test_selector_pack_stem_changes_with_bot_config_path() -> None:
    common = dict(
        mode="quick",
        selectors=["setup_flat:mid:0-2"],
        bot="zem_zev",
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
    )
    no_config = cached_bench._selector_pack_stem(
        bot_config_path=None,
        **common,
    )
    with_config = cached_bench._selector_pack_stem(
        bot_config_path="configs/zem_custom.json",
        **common,
    )
    assert no_config != with_config


def test_run_diag_uses_selected_bot_terminal_metric_namespace() -> None:
    diag = cached_bench._run_diag(
        {
            "state": "landed",
            "setup_gate_projected_dx": 12.0,
            "bot_test_bot_terminal_gate_projected_dx": 4.5,
        },
        bot="test-bot",
    )

    assert diag["setup_gate_projected_dx"] == 12.0
    assert diag["bot_terminal_gate_projected_dx"] == 4.5
    assert diag["bot_terminal_gate_projected_dx_field"] == "bot_test_bot_terminal_gate_projected_dx"
