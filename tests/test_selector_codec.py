from __future__ import annotations

from app.selector import parse_selector
from core.selector_codec import (
    render_record_selector,
    render_selector,
    render_selector_group,
)


def test_render_selector_compact_landing_forms() -> None:
    assert (
        render_selector(
            level_name="setup_flat",
            scenario_name="mid_half",
            goal="landing",
            seed_token=0,
        )
        == "setup_flat:mid_half:0"
    )
    assert (
        render_selector(
            level_name="setup_flat",
            scenario_name=None,
            goal="landing",
            seed_token=0,
        )
        == "setup_flat::0"
    )
    assert (
        render_selector(
            level_name="setup_flat",
            scenario_name="mid_half",
            goal="landing",
            seed_token=None,
        )
        == "setup_flat:mid_half"
    )


def test_render_selector_explicit_non_landing_forms() -> None:
    assert (
        render_selector(
            level_name="setup_downhill",
            scenario_name="mid_half",
            goal="setup",
            seed_token=0,
        )
        == "setup_downhill:mid_half:setup:0"
    )
    assert (
        render_selector_group(
            level_name="setup_downhill",
            scenario_name="mid_half",
            goal="setup",
        )
        == "setup_downhill:mid_half:setup"
    )


def test_render_record_selector_omits_redundant_level_scenario() -> None:
    record = {
        "level": "setup_flat",
        "scenario": "setup_flat",
        "eval_goal": "landing",
        "seed": 3,
    }
    assert render_record_selector(record) == "setup_flat::3"
    assert render_record_selector(record, include_seed=False) == "setup_flat"


def test_parse_selector_contract_unchanged() -> None:
    parsed = parse_selector(
        "setup_climb:high_half:setup:7",
        default_level=None,
        known_levels={"setup_climb", "setup_flat"},
    )
    assert parsed.level_name == "setup_climb"
    assert parsed.scenario_name == "high_half"
    assert parsed.goal == "setup"
    assert parsed.seed_token == "7"
