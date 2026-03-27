from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.benchmark_cache as benchmark_cache
import app.benchmark_compare as benchmark_compare


def _record(
    *,
    level: str,
    scenario: str,
    seed: int,
    state: str,
    success: bool,
    fuel: float,
    ref_gap_area: float = 0.0,
    ref_gap_max: float = 0.0,
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
        "trace_ref_gap_mean": ref_gap_area / 10.0,
        "trace_ref_gap_area": ref_gap_area,
        "trace_ref_gap_max": ref_gap_max,
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


def _expected_cache_meta() -> dict[str, object]:
    return {
        "mode": "quick",
        "selectors": ["boost:flat:mid:half:0-1"],
        "bot": "pdg",
        "trace_detail": "report",
        "bot_config_path": None,
        "worker_mode": "default",
        "bot_profile_enabled": True,
        "bot_profile_interval_s": None,
        "bot_profile_log_lines": False,
    }


def _write_cached_tracepack(
    tmp_path: Path,
    *,
    commit: str = "cand",
    stem: str = "quick_boost_n1_deadbeef00",
    with_trace: bool = True,
    with_preview: bool = True,
) -> tuple[Path, Path, Path, Path, Path]:
    outputs_root = (tmp_path / "outputs").resolve()
    results_root = outputs_root / "benchmarks"
    out_dir = results_root / commit
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = (out_dir / f"{stem}.tracepack.json").resolve()
    meta_path = (out_dir / f"{stem}.meta.json").resolve()
    trace_root = json_path.with_suffix("")
    trace_path = (trace_root / "traces" / "boost_flat_mid_half_0.trace.json").resolve()
    preview_path = (trace_root / "previews" / "boost_flat_mid_half_0.png").resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    if with_trace:
        trace_path.write_text("{}", encoding="utf-8")
    if with_preview:
        preview_path.write_bytes(b"png")
    payload = {
        "schema": "pylander.tracepack.v1",
        "schema_version": 3,
        "trace_detail": "report",
        "trace_root_path": str(trace_root),
        "trace_root_rel": trace_root.relative_to(outputs_root).as_posix(),
        "run_index": [
            {
                "selector": "boost:flat:mid:half:0",
                "run_key": "boost:flat:mid:half:0",
                "run_instance_id": 1,
                "trace_path": str(trace_path),
                "trace_rel_path": trace_path.relative_to(outputs_root).as_posix(),
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": preview_path.relative_to(
                    outputs_root
                ).as_posix(),
            }
        ],
        "records": [
            {
                "level": "boost",
                "scenario": "flat:mid:half",
                "seed": 0,
                "trace_path": str(trace_path),
                "trace_rel_path": trace_path.relative_to(outputs_root).as_posix(),
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": preview_path.relative_to(
                    outputs_root
                ).as_posix(),
            }
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    meta_payload = {
        **_expected_cache_meta(),
        "commit": commit,
        "created_at_utc": "2026-03-23T00:00:00+00:00",
        "json_path": str(json_path),
        "bench_exit_code": 0,
    }
    meta_path.write_text(
        json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return results_root, json_path, meta_path, trace_path, preview_path


def test_observation_only_crash_does_not_mark_notable_regression() -> None:
    baseline = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
            ),
            _record(
                level="terminal",
                scenario="normal:mid",
                seed=0,
                state="landed",
                success=True,
                fuel=30.0,
            ),
        ]
    }
    candidate = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=21.0,
            ),
            _record(
                level="terminal",
                scenario="normal:mid",
                seed=0,
                state="crashed",
                success=False,
                fuel=31.0,
            ),
        ]
    }
    report = benchmark_compare.print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"boost": "normal", "terminal": "observe_only"},
        bot="pdg",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is False
    assert len(report["global"]["crash"]["new_crashes"]) == 0
    assert len(report["observation"]["crash"]["new_crashes"]) == 1


def test_normal_crash_marks_notable_regression() -> None:
    baseline = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
            ),
        ]
    }
    candidate = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="crashed",
                success=False,
                fuel=22.0,
            ),
        ]
    }
    report = benchmark_compare.print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"boost": "normal"},
        bot="pdg",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert len(report["global"]["crash"]["new_crashes"]) == 1


def test_boost_climb_crash_now_gates_global_regressions() -> None:
    baseline = {
        "records": [
            _record(
                level="terminal",
                scenario="normal:mid",
                seed=0,
                state="landed",
                success=True,
                fuel=30.0,
            ),
        ]
    }
    candidate = {
        "records": [
            _record(
                level="terminal",
                scenario="normal:mid",
                seed=0,
                state="crashed",
                success=False,
                fuel=31.0,
            ),
        ]
    }
    report = benchmark_compare.print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"terminal": "normal"},
        bot="pdg",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert len(report["global"]["crash"]["new_crashes"]) == 1
    assert len(report["observation"]["crash"]["new_crashes"]) == 0


def test_scenario_regressions_group_by_level_and_scenario() -> None:
    baseline = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
            ),
            _record(
                level="terminal",
                scenario="error:mid:wide",
                seed=0,
                state="landed",
                success=True,
                fuel=40.0,
            ),
        ]
    }
    candidate = {
        "records": [
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=25.0,
            ),
            _record(
                level="terminal",
                scenario="error:mid:wide",
                seed=0,
                state="landed",
                success=True,
                fuel=35.0,
            ),
        ]
    }

    rows = benchmark_compare.scenario_regressions(baseline, candidate)
    names = {str(item["scenario"]) for item in rows}
    assert names == {"boost:flat:mid:half", "terminal:error:mid:wide"}


def test_scenario_regressions_separate_non_landing_goal_by_selector() -> None:
    baseline = {
        "records": [
            {
                **_record(
                    level="boost",
                    scenario="downhill:mid:half",
                    seed=0,
                    state="flying",
                    success=True,
                    fuel=20.0,
                ),
                "eval_goal": "boost_cutoff",
            }
        ]
    }
    candidate = {
        "records": [
            {
                **_record(
                    level="boost",
                    scenario="downhill:mid:half",
                    seed=0,
                    state="flying",
                    success=False,
                    fuel=24.0,
                ),
                "eval_goal": "boost_cutoff",
            }
        ]
    }

    rows = benchmark_compare.scenario_regressions(baseline, candidate)
    assert [str(item["scenario"]) for item in rows] == [
        "boost:downhill:mid:half:boost_cutoff"
    ]


def test_scenario_regressions_include_reference_gap_deltas() -> None:
    baseline = {
        "records": [
            _record(
                level="terminal",
                scenario="normal:shallower",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
                ref_gap_area=10.0,
                ref_gap_max=4.0,
            ),
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
                ref_gap_area=12.0,
                ref_gap_max=5.0,
            ),
        ]
    }
    candidate = {
        "records": [
            _record(
                level="terminal",
                scenario="normal:shallower",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
                ref_gap_area=28.0,
                ref_gap_max=9.0,
            ),
            _record(
                level="boost",
                scenario="flat:mid:half",
                seed=0,
                state="landed",
                success=True,
                fuel=20.0,
                ref_gap_area=12.0,
                ref_gap_max=5.0,
            ),
        ]
    }

    rows = benchmark_compare.scenario_regressions(baseline, candidate)

    assert rows[0]["scenario"] == "terminal:normal:shallower"
    assert rows[0]["delta_ref_gap_mean"] == pytest.approx(1.8)
    assert rows[0]["delta_ref_gap_area"] == pytest.approx(18.0)
    assert rows[0]["delta_ref_gap_peak_max"] == pytest.approx(5.0)
    assert rows[0]["ref_gap_basis"] == "success_only"


def test_global_compute_regression_marks_notable_regression() -> None:
    baseline = {
        "records": [
            _with_profile(
                _record(
                    level="boost",
                    scenario="flat:mid:half",
                    seed=0,
                    state="landed",
                    success=True,
                    fuel=20.0,
                ),
            )
        ]
    }
    candidate = {
        "records": [
            _with_profile(
                _record(
                    level="boost",
                    scenario="flat:mid:half",
                    seed=0,
                    state="landed",
                    success=True,
                    fuel=20.0,
                ),
                bot_profile_total_ms_per_tick=0.75,
                bot_profile_total_ms_per_tick_p99=1.10,
                bot_profile_update_ms_per_tick_p99=0.34,
            )
        ]
    }

    report = benchmark_compare.print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"boost": "normal"},
        bot="pdg",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is True
    assert report["global"]["compute"]["notable_regression"] is True
    assert report["global"]["compute"]["notable_any"] is True


def test_observation_compute_regression_does_not_gate_global() -> None:
    baseline = {
        "records": [
            _with_profile(
                _record(
                    level="terminal",
                    scenario="normal:mid",
                    seed=0,
                    state="landed",
                    success=True,
                    fuel=20.0,
                ),
            )
        ]
    }
    candidate = {
        "records": [
            _with_profile(
                _record(
                    level="terminal",
                    scenario="normal:mid",
                    seed=0,
                    state="landed",
                    success=True,
                    fuel=20.0,
                ),
                bot_profile_total_ms_per_tick=0.78,
                bot_profile_total_ms_per_tick_p99=1.15,
                bot_profile_update_ms_per_tick_p99=0.36,
            )
        ]
    }

    report = benchmark_compare.print_compare(
        baseline_commit="base",
        candidate_commit="cand",
        baseline_payload=baseline,
        candidate_payload=candidate,
        level_policy={"terminal": "observe_only"},
        bot="pdg",
        crash_detail_limit=2,
    )

    assert report["notable_regression"] is False
    assert report["global"]["compute"]["available"] is False
    assert report["observation"]["compute"]["notable_regression"] is True


def test_selector_pack_stem_changes_with_bot_config_path() -> None:
    no_config = benchmark_cache.selector_pack_stem(
        mode="quick",
        selectors=["boost:flat:mid:half:0-2"],
        bot="pdg",
        trace_detail="report",
        bot_config_path=None,
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
    )
    with_config = benchmark_cache.selector_pack_stem(
        mode="quick",
        selectors=["boost:flat:mid:half:0-2"],
        bot="pdg",
        trace_detail="report",
        bot_config_path="configs/zem_custom.json",
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
    )
    assert no_config != with_config


def test_run_diag_uses_selected_bot_terminal_metric_namespace() -> None:
    diag = benchmark_compare.run_diag(
        {
            "state": "landed",
            "boost_cutoff_projected_dx": 12.0,
            "bot_test_bot_terminal_entry_projected_dx": 4.5,
        },
        bot="test-bot",
    )

    assert diag["boost_cutoff_projected_dx"] == 12.0
    assert diag["bot_terminal_entry_projected_dx"] == 4.5
    assert (
        diag["bot_terminal_entry_projected_dx_field"]
        == "bot_test_bot_terminal_entry_projected_dx"
    )


def test_validate_cached_tracepack_assets_accepts_complete_pack(tmp_path: Path) -> None:
    results_root, json_path, _meta_path, _trace_path, _preview_path = (
        _write_cached_tracepack(tmp_path)
    )

    issue = benchmark_cache.validate_cached_tracepack_assets(
        json_path,
        outputs_root=results_root.parent.resolve(),
    )

    assert issue is None


def test_validate_cached_tracepack_assets_rejects_missing_preview(
    tmp_path: Path,
) -> None:
    results_root, json_path, _meta_path, _trace_path, preview_path = (
        _write_cached_tracepack(
            tmp_path,
            with_preview=False,
        )
    )

    issue = benchmark_cache.validate_cached_tracepack_assets(
        json_path,
        outputs_root=results_root.parent.resolve(),
    )

    assert issue == f"missing preview png for boost:flat:mid:half:0: {preview_path}"


def test_load_or_run_reuses_complete_cache(tmp_path: Path) -> None:
    results_root, json_path, meta_path, _trace_path, _preview_path = (
        _write_cached_tracepack(tmp_path)
    )

    loaded_json, loaded_meta, cached = benchmark_cache.load_or_run(
        commit="cand",
        stem="quick_boost_n1_deadbeef00",
        mode="quick",
        selectors=["boost:flat:mid:half:0-1"],
        bot="pdg",
        trace_detail="report",
        bot_config_path=None,
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
        results_root=results_root,
        reuse=True,
        allow_run=True,
        command_builder=lambda **_kwargs: ["bench"],
    )

    assert cached is True
    assert loaded_json == json_path
    assert loaded_meta == meta_path


def test_load_or_run_rejects_incomplete_cache_when_rerun_is_disallowed(
    tmp_path: Path,
) -> None:
    results_root, _json_path, _meta_path, trace_path, _preview_path = (
        _write_cached_tracepack(
            tmp_path,
            with_trace=False,
        )
    )

    with pytest.raises(
        SystemExit, match="Incomplete cache for commit cand: missing trace json"
    ):
        benchmark_cache.load_or_run(
            commit="cand",
            stem="quick_boost_n1_deadbeef00",
            mode="quick",
            selectors=["boost:flat:mid:half:0-1"],
            bot="pdg",
            trace_detail="report",
            bot_config_path=None,
            bot_profile_enabled=True,
            bot_profile_interval_s=None,
            bot_profile_log_lines=False,
            results_root=results_root,
            reuse=True,
            allow_run=False,
            command_builder=lambda **_kwargs: ["bench"],
        )

    assert not trace_path.exists()


def test_load_or_run_reruns_when_cached_trace_assets_are_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    results_root, json_path, meta_path, trace_path, preview_path = (
        _write_cached_tracepack(
            tmp_path,
            with_trace=False,
            with_preview=False,
        )
    )

    def _fake_run_command(_cmd: list[str]) -> tuple[int, str]:
        trace_path.write_text("{}", encoding="utf-8")
        preview_path.write_bytes(b"png")
        return 0, ""

    monkeypatch.setattr(benchmark_cache, "run_command", _fake_run_command)

    loaded_json, loaded_meta, cached = benchmark_cache.load_or_run(
        commit="cand",
        stem="quick_boost_n1_deadbeef00",
        mode="quick",
        selectors=["boost:flat:mid:half:0-1"],
        bot="pdg",
        trace_detail="report",
        bot_config_path=None,
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
        results_root=results_root,
        reuse=True,
        allow_run=True,
        command_builder=lambda **_kwargs: ["bench"],
    )

    assert cached is False
    assert loaded_json == json_path
    assert loaded_meta == meta_path
    assert trace_path.exists()
    assert preview_path.exists()
