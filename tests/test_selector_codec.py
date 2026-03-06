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
            level_name="launch",
            scenario_name="mid",
            goal="landing",
            seed_token=0,
        )
        == "launch:mid:0"
    )
    assert (
        render_selector(
            level_name="launch",
            scenario_name=None,
            goal="landing",
            seed_token=0,
        )
        == "launch::0"
    )
    assert (
        render_selector(
            level_name="launch",
            scenario_name="mid",
            goal="landing",
            seed_token=None,
        )
        == "launch:mid"
    )


def test_render_selector_explicit_non_landing_forms() -> None:
    assert (
        render_selector(
            level_name="setup",
            scenario_name="mid_near",
            goal="setup",
            seed_token=0,
        )
        == "setup:mid_near:setup:0"
    )
    assert (
        render_selector_group(
            level_name="setup",
            scenario_name="mid_near",
            goal="setup",
        )
        == "setup:mid_near:setup"
    )


def test_render_record_selector_omits_redundant_level_scenario() -> None:
    record = {
        "level": "launch",
        "scenario": "launch",
        "eval_goal": "landing",
        "seed": 3,
    }
    assert render_record_selector(record) == "launch::3"
    assert render_record_selector(record, include_seed=False) == "launch"


def test_parse_selector_contract_unchanged() -> None:
    parsed = parse_selector(
        "climb:slope_high:setup:7",
        default_level=None,
        known_levels={"climb", "launch"},
    )
    assert parsed.level_name == "climb"
    assert parsed.scenario_name == "slope_high"
    assert parsed.goal == "setup"
    assert parsed.seed_token == "7"
