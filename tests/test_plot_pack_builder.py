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


plot_pack = _load_module(
    "plot_pack_builder_script",
    _script("skills/pylander-plot-runner/scripts/build_plot_pack.py"),
)


def test_build_cases_from_records_uses_selected_bot_terminal_metric_namespace() -> None:
    cases = plot_pack._build_cases_from_records(
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
    assert evidence["bot_terminal_entry_projected_dx_field"] == "bot_test_bot_terminal_entry_projected_dx"


def test_extract_paths_reads_plot_table_metadata() -> None:
    payload = plot_pack._extract_paths(
        """
[Plot Files]
path                  outputs/plots/overview/case_a.png
path                  outputs/plots/case_a/spatial_speed.png
manifest              outputs/plots/case_a/manifest.json
bundle_dir            outputs/plots/case_a
"""
    )

    assert payload["plot_paths"] == [
        "outputs/plots/overview/case_a.png",
        "outputs/plots/case_a/spatial_speed.png",
    ]
    assert payload["plot_manifest_path"] == "outputs/plots/case_a/manifest.json"
    assert payload["plot_bundle_dir"] == "outputs/plots/case_a"


def test_resolve_plot_workers_uses_auto_default(monkeypatch) -> None:
    monkeypatch.setattr(plot_pack.os, "cpu_count", lambda: 24)

    assert plot_pack._resolve_plot_workers(0) == 16
    assert plot_pack._resolve_plot_workers(None) == 16
    assert plot_pack._resolve_plot_workers(3) == 3
