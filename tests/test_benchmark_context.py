from __future__ import annotations

from pathlib import Path

import bot_framework.benchmark_context as benchmark_context
from bot_framework.selector_pack import ResolvedSelectorPack


def test_resolve_auto_baseline_skips_only_irrelevant_commits(
    monkeypatch,
) -> None:
    monkeypatch.setattr(benchmark_context, "_safe_parent_ref", lambda ref: "HEAD^")
    monkeypatch.setattr(
        benchmark_context,
        "first_parent_commits",
        lambda start_ref, limit=24: ["docs1", "bench1", "bot1"],
    )
    monkeypatch.setattr(
        benchmark_context,
        "git_rev_parse",
        lambda ref: {
            "docs1": "aa11bb2",
            "bench1": "cc33dd4",
            "bot1": "ee55ff6",
        }.get(ref, ref),
    )
    monkeypatch.setattr(
        benchmark_context,
        "commit_changed_files",
        lambda commit: {
            "docs1": ["README.md"],
            "bench1": ["tooling/trace_bundle.py", "tests/test_bench_bundle.py"],
            "bot1": ["bots/pdg.py"],
        }[commit],
    )
    monkeypatch.setattr(
        benchmark_context,
        "_commit_subject",
        lambda commit: {
            "docs1": "docs: clarify benchmark workflow",
            "bench1": "refactor: simplify bundle reporting",
            "bot1": "feat: tune terminal flare gating",
        }[commit],
    )

    result = benchmark_context.resolve_auto_baseline(dirty=False)

    assert result["start_ref"] == "HEAD^"
    assert result["resolved_commit"] == "ee55ff6"
    assert [item["commit"] for item in result["skipped_commits"]] == [
        "aa11bb2",
        "cc33dd4",
    ]
    assert result["inspected_commits"][0]["skip_candidate"] is True
    assert result["inspected_commits"][-1]["skip_candidate"] is False


def test_build_auto_intent_records_context_and_auto_baseline(
    tmp_path: Path,
) -> None:
    inspect_payload = {
        "repo_context": {
            "workspace_key": "4869be4-dirty-97df1b28ee",
            "changed_files": ["bots/pdg.py"],
            "touched_areas": ["bot_logic"],
        },
        "baseline": {
            "explicit_commit": None,
            "auto": {
                "resolved_commit": "5225400",
                "skipped_commits": [
                    {
                        "commit": "ce8fed5",
                        "skip_reason": "changed files are limited to docs, skills, tests, or benchmark tooling",
                        "subject": "refactor: unify benchmark workflow cli",
                    }
                ],
            },
        },
    }
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )

    payload, sidecar_path = benchmark_context.build_auto_intent(
        inspect_payload=inspect_payload,
        pack=pack,
        mode="focused",
        seed_spec="0-4",
        bot="pdg",
        trace_detail="report",
        bot_config_path=None,
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
        baseline_ref="auto",
        missing_baseline_policy="seed",
        results_root=tmp_path / "outputs" / "benchmarks",
        goal_summary="Validate boost retune against the last behavior change",
        context_notes=["User asked for a focused boost regression check."],
    )

    assert (
        payload["goal_summary"]
        == "Validate boost retune against the last behavior change"
    )
    assert payload["conversation_context"] == [
        "User asked for a focused boost regression check."
    ]
    assert payload["baseline_plan"]["strategy"] == "auto"
    assert payload["baseline_plan"]["missing_baseline_policy"] == "seed"
    assert payload["baseline_plan"]["resolved_ref"] == "5225400"
    assert payload["outputs"]["candidate_commit"] == "4869be4-dirty-97df1b28ee"
    assert payload["outputs"]["candidate_json"].endswith(".tracepack.json")
    assert payload["outputs"]["intent_json"] == str(sidecar_path)
    assert sidecar_path.name.endswith(".intent.json")


def test_build_auto_intent_defaults_explicit_baseline_to_error(
    tmp_path: Path,
) -> None:
    inspect_payload = {
        "repo_context": {
            "workspace_key": "4869be4-dirty-97df1b28ee",
            "changed_files": ["bots/pdg.py"],
            "touched_areas": ["bot_logic"],
        },
        "baseline": {
            "explicit_commit": "5225400",
            "auto": {"resolved_commit": "ignored", "skipped_commits": []},
        },
    }
    pack = ResolvedSelectorPack(
        selectors=["boost:flat:mid:half:0-4"],
        effective_level_policy={"boost": "normal"},
        included_levels=["boost"],
        excluded_levels_effective=[],
        observe_only_levels_effective=[],
    )

    payload, _sidecar_path = benchmark_context.build_auto_intent(
        inspect_payload=inspect_payload,
        pack=pack,
        mode="quick",
        seed_spec=None,
        bot="pdg",
        trace_detail="report",
        bot_config_path=None,
        bot_profile_enabled=True,
        bot_profile_interval_s=None,
        bot_profile_log_lines=False,
        baseline_ref="5225400",
        missing_baseline_policy="",
        results_root=tmp_path / "outputs" / "benchmarks",
    )

    assert payload["baseline_plan"]["strategy"] == "explicit"
    assert payload["baseline_plan"]["missing_baseline_policy"] == "error"
    assert payload["baseline_plan"]["resolved_ref"] == "5225400"
