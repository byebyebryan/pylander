from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pylander-benchmark"
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


def test_observation_only_crash_does_not_mark_notable_regression() -> None:
    baseline = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            _record(level="climb", scenario="slope_mid", seed=0, state="landed", success=True, fuel=30.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="landed", success=True, fuel=21.0),
            _record(level="climb", scenario="slope_mid", seed=0, state="crashed", success=False, fuel=31.0),
        ]
    }
    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"launch": "normal", "climb": "observe_only"},
        bot="zem_zev",
        eval_mode="auto",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is False
    assert len(report["global"]["crash"]["new_crashes"]) == 0
    assert len(report["observation"]["crash"]["new_crashes"]) == 1


def test_normal_crash_marks_notable_regression() -> None:
    baseline = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="crashed", success=False, fuel=22.0),
        ]
    }
    report = cached_bench._print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"launch": "normal"},
        bot="zem_zev",
        eval_mode="auto",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert len(report["global"]["crash"]["new_crashes"]) == 1


def test_scenario_regressions_group_by_level_and_scenario() -> None:
    baseline = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="landed", success=True, fuel=20.0),
            _record(level="coast", scenario="mid", seed=0, state="landed", success=True, fuel=40.0),
        ]
    }
    candidate = {
        "records": [
            _record(level="launch", scenario="mid", seed=0, state="landed", success=True, fuel=25.0),
            _record(level="coast", scenario="mid", seed=0, state="landed", success=True, fuel=35.0),
        ]
    }

    rows = cached_bench._scenario_regressions(baseline, candidate)
    names = {str(item["scenario"]) for item in rows}
    assert names == {"launch:mid", "coast:mid"}
