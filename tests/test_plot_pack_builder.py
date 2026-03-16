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
