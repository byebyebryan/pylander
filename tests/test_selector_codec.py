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
            level_name="boost_flat",
            scenario_name="mid_half",
            goal="landing",
            seed_token=0,
        )
        == "boost_flat:mid_half:0"
    )
    assert (
        render_selector(
            level_name="boost_flat",
            scenario_name=None,
            goal="landing",
            seed_token=0,
        )
        == "boost_flat::0"
    )
    assert (
        render_selector(
            level_name="boost_flat",
            scenario_name="mid_half",
            goal="landing",
            seed_token=None,
        )
        == "boost_flat:mid_half"
    )


def test_render_selector_explicit_non_landing_forms() -> None:
    assert (
        render_selector(
            level_name="boost_downhill",
            scenario_name="mid_half",
            goal="boost",
            seed_token=0,
        )
        == "boost_downhill:mid_half:boost:0"
    )
    assert (
        render_selector_group(
            level_name="boost_downhill",
            scenario_name="mid_half",
            goal="boost",
        )
        == "boost_downhill:mid_half:boost"
    )


def test_render_record_selector_omits_redundant_level_scenario() -> None:
    record = {
        "level": "boost_flat",
        "scenario": "boost_flat",
        "eval_goal": "landing",
        "seed": 3,
    }
    assert render_record_selector(record) == "boost_flat::3"
    assert render_record_selector(record, include_seed=False) == "boost_flat"


def test_parse_selector_contract_unchanged() -> None:
    parsed = parse_selector(
        "boost_climb:high_half:boost:7",
        default_level=None,
        known_levels={"boost_climb", "boost_flat"},
    )
    assert parsed.level_name == "boost_climb"
    assert parsed.scenario_name == "high_half"
    assert parsed.goal == "boost"
    assert parsed.seed_token == "7"
