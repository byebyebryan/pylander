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
    assert "setup_climb" in pack.observe_only_levels_effective
    assert "flat" in pack.excluded_levels_effective
    assert "mountains" in pack.excluded_levels_effective
    assert len(pack.selectors) == 6


def test_auto_mode_exclude_override_removes_level() -> None:
    pack = selector_pack.build_selectors(
        mode="quick",
        exclude_levels=["setup_downhill"],
    )
    assert "setup_downhill" in pack.excluded_levels_effective
    assert all(not item.startswith("setup_downhill:") for item in pack.selectors)


def test_auto_mode_observe_override_marks_level() -> None:
    pack = selector_pack.build_selectors(
        mode="quick",
        observe_only_levels=["setup_flat"],
    )
    assert pack.effective_level_policy["setup_flat"] == "observe_only"
    assert "setup_flat" in pack.observe_only_levels_effective


def test_policy_override_conflict_errors() -> None:
    with pytest.raises(ValueError, match="both excluded and observe-only"):
        selector_pack.build_selectors(
            mode="smoke",
            exclude_levels=["setup_flat"],
            observe_only_levels=["setup_flat"],
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
        focused_selectors=["flat::0"],
    )
    assert pack.selectors == ["flat::0"]
    assert pack.effective_level_policy["flat"] == "excluded"


def test_focused_selector_unknown_scenario_errors() -> None:
    with pytest.raises(ValueError, match="Unknown scenario 'not_real'"):
        selector_pack.build_selectors(
            mode="focused",
            focused_selectors=["setup_flat:not_real:0"],
        )


def test_focused_selector_preserves_csv_seed_specs() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["setup_flat:mid:0,2"],
    )
    assert pack.selectors == ["setup_flat:mid:0,2"]


def test_focused_selector_preserves_goal_slot() -> None:
    pack = selector_pack.build_selectors(
        mode="focused",
        focused_selectors=["setup_flat:mid:setup:0-2"],
    )
    assert pack.selectors == ["setup_flat:mid:setup:0-2"]


def test_build_bench_command_includes_profile_flags() -> None:
    cmd = selector_pack.build_bench_command(
        selectors=["setup_flat:mid:0-1"],
        bot_profile_enabled=True,
        bot_profile_interval_s=1.25,
        bot_profile_log_lines=False,
    )
    assert "--workers" not in cmd
    assert "--bot-profile" in cmd
    assert "--no-bot-profile-logs" in cmd
    assert "--bot-profile-interval-s" in cmd
    assert "1.250" in cmd


def test_build_bench_command_includes_bot_config_path() -> None:
    cmd = selector_pack.build_bench_command(
        selectors=["setup_flat:mid:0-1"],
        bot_config_path="configs/zem_fast.json",
    )
    assert "--bot-config" in cmd
    idx = cmd.index("--bot-config")
    assert cmd[idx + 1] == "configs/zem_fast.json"
