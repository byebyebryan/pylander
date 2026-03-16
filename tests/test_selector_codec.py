from __future__ import annotations

import pytest

from app.selector import parse_selector
from core.selector_codec import (
    render_record_selector,
    render_selector,
    render_selector_group,
)


def test_render_selector_compact_landing_forms() -> None:
    assert (
        render_selector(
            level_name="boost",
            scenario_name="flat:mid:half",
            goal="landing",
            seed_token=0,
        )
        == "boost:flat:mid:half:0"
    )
    assert (
        render_selector(
            level_name="boost",
            scenario_name=None,
            goal="landing",
            seed_token=0,
        )
        == "boost:0"
    )
    assert (
        render_selector(
            level_name="boost",
            scenario_name="flat:mid:half",
            goal="landing",
            seed_token=None,
        )
        == "boost:flat:mid:half"
    )


def test_render_selector_explicit_non_landing_forms() -> None:
    assert (
        render_selector(
            level_name="boost",
            scenario_name="downhill:mid:half",
            goal="boost_cutoff",
            seed_token=0,
        )
        == "boost:downhill:mid:half:boost_cutoff:0"
    )
    assert (
        render_selector_group(
            level_name="boost",
            scenario_name="downhill:mid:half",
            goal="boost_cutoff",
        )
        == "boost:downhill:mid:half:boost_cutoff"
    )


def test_render_record_selector_omits_redundant_level_scenario() -> None:
    record = {
        "level": "boost",
        "scenario": "boost",
        "eval_goal": "landing",
        "seed": 3,
    }
    assert render_record_selector(record) == "boost:3"
    assert render_record_selector(record, include_seed=False) == "boost"


def test_parse_selector_uses_layered_contract() -> None:
    parsed = parse_selector(
        "boost:climb:high:half:boost_cutoff:7",
        default_level=None,
        known_levels={"boost", "flat"},
    )
    assert parsed.level_name == "boost"
    assert parsed.scenario_name == "climb:high:half"
    assert parsed.scenario_path == ("climb", "high", "half")
    assert parsed.goal == "boost_cutoff"
    assert parsed.seed_token == "7"


def test_parse_selector_rejects_old_boost_goal_token_with_migration_hint() -> None:
    with pytest.raises(ValueError, match="boost_cutoff"):
        parse_selector(
            "boost:climb:high:half:boost:7",
            default_level=None,
            known_levels={"boost", "flat"},
        )
