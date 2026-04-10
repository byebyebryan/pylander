from __future__ import annotations

import sys

import pytest

import tooling.plot_pack as plot_pack


def test_build_cases_from_records_uses_selected_bot_terminal_metric_namespace() -> None:
    cases = plot_pack.build_cases_from_records(
        [
            {
                "level": "launch",
                "scenario": "far",
                "seed": 0,
                "state": "landed",
                "boost_cutoff_projected_dx": 12.0,
                "bot_test_bot_terminal_entry_projected_dx": 4.5,
                "fuel_consumed": 18.0,
            }
        ],
        top_n=4,
        bot="test-bot",
    )

    assert len(cases) == 1
    evidence = dict(cases[0]["evidence"])
    assert evidence["boost_cutoff_projected_dx"] == 12.0
    assert evidence["bot_terminal_entry_projected_dx"] == 4.5
    assert (
        evidence["bot_terminal_entry_projected_dx_field"]
        == "bot_test_bot_terminal_entry_projected_dx"
    )


def test_extract_trace_assets_reads_trace_file_metadata() -> None:
    payload = plot_pack.extract_trace_assets(
        """
[Trace Files]
trace_path            outputs/traces/case_a/traces/case_a.trace.json
trace_rel_path        traces/case_a/traces/case_a.trace.json
preview_path          outputs/traces/case_a/previews/case_a.png
preview_rel_path      traces/case_a/previews/case_a.png
"""
    )

    assert payload == {
        "trace_path": "outputs/traces/case_a/traces/case_a.trace.json",
        "trace_rel_path": "traces/case_a/traces/case_a.trace.json",
        "trace_preview_path": "outputs/traces/case_a/previews/case_a.png",
        "trace_preview_rel_path": "traces/case_a/previews/case_a.png",
    }


def test_assign_case_keys_preserves_unique_selector_instances() -> None:
    assigned = plot_pack.assign_case_keys(
        [
            {"selector": "plunge:low:half:0"},
            {"selector": "plunge:low:half:0"},
            {"selector": "plunge:mid:half:0"},
        ]
    )

    assert [case["run_key"] for case in assigned] == [
        "plunge:low:half:0#1",
        "plunge:low:half:0#2",
        "plunge:mid:half:0",
    ]
    assert [case["run_instance_id"] for case in assigned] == [1, 2, 1]


def test_main_compare_mode_requires_compare_json(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["build_plot_pack.py", "--mode", "compare"],
    )

    with pytest.raises(SystemExit, match="compare mode requires --compare-json"):
        plot_pack.main()


def test_resolve_plot_workers_uses_auto_default(monkeypatch) -> None:
    monkeypatch.setattr(plot_pack.os, "cpu_count", lambda: 24)

    assert plot_pack.resolve_plot_workers(0) == 16
    assert plot_pack.resolve_plot_workers(None) == 16
    assert plot_pack.resolve_plot_workers(3) == 3


def test_plot_command_includes_trace_detail() -> None:
    cmd = plot_pack.plot_command(
        "plunge:low:half:0",
        bot="pdg",
        trace_sample_period_s=0.25,
        trace_detail="debug",
    )

    assert "--trace-detail" in cmd
    assert cmd[cmd.index("--trace-detail") + 1] == "debug"
