from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "pylander-benchmark-runner"
    / "scripts"
)
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import build_selector_pack as selector_pack  # noqa: E402


def test_smoke_pack_uses_profile_policies() -> None:
    pack = selector_pack.build_selectors(mode="smoke")
    assert all(not item.startswith("flat") for item in pack.selectors)
    assert all(not item.startswith("mountains") for item in pack.selectors)
    assert "boost" not in pack.observe_only_levels_effective
    assert pack.effective_level_policy["boost"] == "normal"
    assert "flat" in pack.excluded_levels_effective
    assert "mountains" in pack.excluded_levels_effective
    assert len(pack.selectors) == 6


def test_auto_mode_exclude_override_removes_level() -> None:
    pack = selector_pack.build_selectors(
        mode="quick",
        exclude_levels=["boost"],
    )
    assert "boost" in pack.excluded_levels_effective
    assert all(not item.startswith("boost:") for item in pack.selectors)


def test_auto_mode_observe_override_marks_level() -> None:
    pack = selector_pack.build_selectors(
        mode="quick",
        observe_only_levels=["boost"],
    )
    assert pack.effective_level_policy["boost"] == "observe_only"
    assert "boost" in pack.observe_only_levels_effective


def test_policy_override_conflict_errors() -> None:
    with pytest.raises(ValueError, match="both excluded and observe-only"):
        selector_pack.build_selectors(
            mode="smoke",
            exclude_levels=["boost"],
            observe_only_levels=["boost"],
        )


def test_policy_override_unknown_level_errors() -> None:
    with pytest.raises(ValueError, match="Unknown level 'not_a_level'"):
        selector_pack.build_selectors(
            mode="smoke",
            exclude_levels=["not_a_level"],
        )


def test_focused_selector_explicit_level_wins_even_if_excluded() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["flat:0"],
    )
    assert pack.selectors == ["flat:0"]
    assert pack.effective_level_policy["flat"] == "excluded"


def test_focused_selector_without_layers_uses_defaults() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["boost:0"],
    )
    assert pack.selectors == ["boost:0"]


def test_focused_selector_unknown_scenario_errors() -> None:
    with pytest.raises(ValueError, match="Unknown scenario 'flat:not_real'"):
        selector_pack.build_selectors(
            mode="focused",
            focused_selectors=["boost:flat:not_real:0"],
        )


def test_focused_selector_preserves_csv_seed_specs() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["boost:flat:mid:half:0,2"],
    )
    assert pack.selectors == ["boost:flat:mid:half:0,2"]


def test_focused_selector_preserves_goal_slot() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["boost:flat:mid:half:boost_cutoff:0-2"],
    )
    assert pack.selectors == ["boost:flat:mid:half:boost_cutoff:0-2"]


def test_focused_selector_group_flare_excludes_plunge() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["@terminal"],
    )
    assert pack.included_levels == ["terminal"]
    assert all(item.startswith("terminal:") for item in pack.selectors)
    assert all(not item.startswith("plunge:") for item in pack.selectors)


def test_focused_selector_group_plunge_is_separate() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["@plunge"],
    )
    assert pack.included_levels == ["plunge"]
    assert all(item.startswith("plunge:") for item in pack.selectors)


def test_unknown_focused_selector_group_errors() -> None:
    with pytest.raises(ValueError, match="Unknown focused selector group '@not_real'"):
        selector_pack.build_selectors(
            mode="focused",
            focused_selectors=["@not_real"],
        )


def test_build_bench_command_includes_profile_flags() -> None:
    cmd = selector_pack.build_bench_command(
        selectors=["boost:flat:mid:half:0-1"],
        bot_profile_enabled=True,
        bot_profile_interval_s=1.25,
        bot_profile_log_lines=False,
    )
    assert "--workers" not in cmd
    assert "--csv" not in cmd
    assert "--bot-profile" in cmd
    assert "--no-bot-profile-logs" in cmd
    assert "--bot-profile-interval-s" in cmd
    assert "1.250" in cmd


def test_build_bench_command_includes_bot_config_path() -> None:
    cmd = selector_pack.build_bench_command(
        selectors=["boost:flat:mid:half:0-1"],
        bot_config_path="configs/zem_fast.json",
    )
    assert "--bot-config" in cmd
    idx = cmd.index("--bot-config")
    assert cmd[idx + 1] == "configs/zem_fast.json"
