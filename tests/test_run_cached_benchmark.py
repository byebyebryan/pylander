from __future__ import annotations

import json
from pathlib import Path

import app.run_cached_benchmark as run_cached_benchmark
from app.selector_pack import ResolvedSelectorPack


def test_auto_baseline_missing_cache_falls_back_to_candidate_only(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    intent_path = tmp_path / "candidate.tracepack.intent.json"
    intent_payload = {
        "repo_context": {"workspace_key": "cand123"},
        "run_plan": {
            "mode": "quick",
            "bot": "pdg",
            "trace_detail": "report",
            "bot_profile_enabled": True,
            "bot_profile_interval_s": None,
            "bot_profile_log_lines": False,
        },
        "baseline_plan": {
            "strategy": "auto",
            "requested_ref": "auto",
            "missing_baseline_policy": "skip",
            "resolved_ref": "base123",
        },
        "assumptions": [],
    }
    intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )
    candidate_json = tmp_path / "candidate.tracepack.json"
    candidate_meta = tmp_path / "candidate.meta.json"
    candidate_json.write_text(json.dumps({"records": [], "summary": {}}), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run_cached_benchmark,
        "_resolve_inputs",
        lambda args, repo_root: (
            pack,
            intent_payload,
            intent_path,
            "base123",
            "cand123",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        run_cached_benchmark,
        "selector_pack_stem",
        lambda **kwargs: "quick_boost_n1_deadbeef00",
    )

    def _fake_load_or_run(**kwargs):
        if kwargs["commit"] == "cand123":
            return candidate_json, candidate_meta, False
        raise SystemExit(
            "Missing cache for commit base123: quick_boost_n1_deadbeef00.tracepack.json. "
            "Run this pack from that commit once to seed cache."
        )

    monkeypatch.setattr(run_cached_benchmark, "load_or_run", _fake_load_or_run)
    monkeypatch.setattr(
        run_cached_benchmark, "load_json", lambda path: {"records": [], "summary": {}}
    )

    run_cached_benchmark.main(["--intent-json", str(intent_path)])

    output = capsys.readouterr().out
    updated_intent = json.loads(intent_path.read_text(encoding="utf-8"))

    assert "# candidate" in output
    assert "# baseline" in output
    assert "status=missing_cache" in output
    assert updated_intent["assumptions"] == [
        "Missing baseline compare was skipped because the resolved baseline cache (base123) is not available locally."
    ]


def test_missing_baseline_seed_uses_worktree_seed_and_continues(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    intent_path = tmp_path / "candidate.tracepack.intent.json"
    intent_payload = {
        "repo_context": {"workspace_key": "cand123"},
        "run_plan": {
            "mode": "quick",
            "bot": "pdg",
            "trace_detail": "report",
            "bot_profile_enabled": True,
            "bot_profile_interval_s": None,
            "bot_profile_log_lines": False,
        },
        "baseline_plan": {
            "strategy": "auto",
            "requested_ref": "auto",
            "missing_baseline_policy": "seed",
            "resolved_ref": "base123",
        },
        "assumptions": [],
    }
    intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )
    candidate_json = tmp_path / "candidate.tracepack.json"
    candidate_meta = tmp_path / "candidate.meta.json"
    baseline_json = tmp_path / "baseline.tracepack.json"
    baseline_meta = tmp_path / "baseline.meta.json"
    candidate_json.write_text(json.dumps({"records": [], "summary": {}}), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")
    baseline_json.write_text(json.dumps({"records": [], "summary": {}}), encoding="utf-8")
    baseline_meta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run_cached_benchmark,
        "_resolve_inputs",
        lambda args, repo_root: (
            pack,
            intent_payload,
            intent_path,
            "base123",
            "cand123",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        run_cached_benchmark,
        "selector_pack_stem",
        lambda **kwargs: "quick_boost_n1_deadbeef00",
    )

    calls: list[tuple[str, str]] = []

    def _fake_load_or_run(**kwargs):
        calls.append(("load_or_run", kwargs["commit"]))
        if kwargs["commit"] == "cand123":
            return candidate_json, candidate_meta, False
        raise SystemExit(
            "Missing cache for commit base123: quick_boost_n1_deadbeef00.tracepack.json. "
            "Run this pack from that commit once to seed cache."
        )

    monkeypatch.setattr(run_cached_benchmark, "load_or_run", _fake_load_or_run)
    monkeypatch.setattr(
        run_cached_benchmark,
        "seed_cache_from_worktree",
        lambda **kwargs: (
            calls.append(("seed_cache_from_worktree", kwargs["commit"])) or (baseline_json, baseline_meta, False)
        ),
    )
    monkeypatch.setattr(
        run_cached_benchmark, "load_json", lambda path: {"records": [], "summary": {}}
    )
    monkeypatch.setattr(
        run_cached_benchmark,
        "print_compare",
        lambda **kwargs: {
            "notable_regression": False,
            "baseline_commit": "base123",
            "candidate_commit": "cand123",
            "global": {
                "crash": {"new_crashes": []},
                "worst_scenarios": [],
                "compute": {},
            },
        },
    )

    run_cached_benchmark.main(["--intent-json", str(intent_path)])

    output = capsys.readouterr().out

    assert ("seed_cache_from_worktree", "base123") in calls
    assert "# compare_report" in output
    compare_files = sorted(tmp_path.glob("*.compare_vs_*.json"))
    assert compare_files
    compare_payload = json.loads(compare_files[0].read_text(encoding="utf-8"))
    assert compare_payload["baseline_json_path"] == str(baseline_json.resolve())
    assert compare_payload["candidate_json_path"] == str(candidate_json.resolve())


def test_missing_baseline_error_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intent_path = tmp_path / "candidate.tracepack.intent.json"
    intent_payload = {
        "repo_context": {"workspace_key": "cand123"},
        "run_plan": {
            "mode": "quick",
            "bot": "pdg",
            "trace_detail": "report",
            "bot_profile_enabled": True,
            "bot_profile_interval_s": None,
            "bot_profile_log_lines": False,
        },
        "baseline_plan": {
            "strategy": "auto",
            "requested_ref": "auto",
            "missing_baseline_policy": "error",
            "resolved_ref": "base123",
        },
        "assumptions": [],
    }
    intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )
    candidate_json = tmp_path / "candidate.tracepack.json"
    candidate_meta = tmp_path / "candidate.meta.json"
    candidate_json.write_text(json.dumps({"records": [], "summary": {}}), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run_cached_benchmark,
        "_resolve_inputs",
        lambda args, repo_root: (
            pack,
            intent_payload,
            intent_path,
            "base123",
            "cand123",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        run_cached_benchmark,
        "selector_pack_stem",
        lambda **kwargs: "quick_boost_n1_deadbeef00",
    )

    def _fake_load_or_run(**kwargs):
        if kwargs["commit"] == "cand123":
            return candidate_json, candidate_meta, False
        raise SystemExit(
            "Missing cache for commit base123: quick_boost_n1_deadbeef00.tracepack.json. "
            "Run this pack from that commit once to seed cache."
        )

    monkeypatch.setattr(run_cached_benchmark, "load_or_run", _fake_load_or_run)
    monkeypatch.setattr(
        run_cached_benchmark, "load_json", lambda path: {"records": [], "summary": {}}
    )

    try:
        run_cached_benchmark.main(["--intent-json", str(intent_path)])
    except SystemExit as exc:
        assert "Missing cache for commit base123" in str(exc)
    else:
        raise AssertionError("Expected missing baseline error to propagate")


def test_explicit_baseline_without_policy_defaults_to_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intent_path = tmp_path / "candidate.tracepack.intent.json"
    intent_payload = {
        "repo_context": {"workspace_key": "cand123"},
        "run_plan": {
            "mode": "quick",
            "bot": "pdg",
            "trace_detail": "report",
            "bot_profile_enabled": True,
            "bot_profile_interval_s": None,
            "bot_profile_log_lines": False,
        },
        "baseline_plan": {
            "strategy": "explicit",
            "requested_ref": "base123",
            "resolved_ref": "base123",
        },
        "assumptions": [],
    }
    intent_path.write_text(json.dumps(intent_payload), encoding="utf-8")
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )
    candidate_json = tmp_path / "candidate.tracepack.json"
    candidate_meta = tmp_path / "candidate.meta.json"
    candidate_json.write_text(json.dumps({"records": [], "summary": {}}), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        run_cached_benchmark,
        "_resolve_inputs",
        lambda args, repo_root: (
            pack,
            intent_payload,
            intent_path,
            "base123",
            "cand123",
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        run_cached_benchmark,
        "selector_pack_stem",
        lambda **kwargs: "quick_boost_n1_deadbeef00",
    )

    def _fake_load_or_run(**kwargs):
        if kwargs["commit"] == "cand123":
            return candidate_json, candidate_meta, False
        raise SystemExit(
            "Missing cache for commit base123: quick_boost_n1_deadbeef00.tracepack.json. "
            "Run this pack from that commit once to seed cache."
        )

    monkeypatch.setattr(run_cached_benchmark, "load_or_run", _fake_load_or_run)
    monkeypatch.setattr(
        run_cached_benchmark, "load_json", lambda path: {"records": [], "summary": {}}
    )

    try:
        run_cached_benchmark.main(["--intent-json", str(intent_path)])
    except SystemExit as exc:
        assert "Missing cache for commit base123" in str(exc)
    else:
        raise AssertionError("Expected explicit baseline to default to error")
