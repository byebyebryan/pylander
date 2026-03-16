from __future__ import annotations

import pytest

from core.level_capabilities import (
    BenchmarkScenarioSets,
    LevelBenchmarkProfile,
    level_name_tag,
    level_plot_max_side_px,
    level_plot_mode,
    level_plot_output,
    level_scenario_tag,
    list_batch_scenarios_safe,
    resolve_default_bot_name,
    resolve_level_eval_goals,
    resolve_level_benchmark_profile,
    scenario_has_randomized_fields_safe,
    set_benchmark_mode_checked,
    set_eval_goal_checked,
    set_eval_scenario_checked,
)
from levels import create_level, list_available_levels


def test_resolve_default_bot_name_normalizes_whitespace() -> None:
    class _Level:
        default_bot_name = "  pdg  "

    assert resolve_default_bot_name(_Level()) == "pdg"


def test_set_eval_scenario_checked_requires_capability() -> None:
    class _NoScenario:
        pass

    with pytest.raises(ValueError, match="does not support scenario selection"):
        set_eval_scenario_checked(_NoScenario(), "mid")


def test_resolve_level_eval_goals_defaults_to_landing() -> None:
    class _Level:
        pass

    assert resolve_level_eval_goals(_Level()) == ("landing",)


def test_level_eval_goal_support_matches_declared_catalogs() -> None:
    assert resolve_level_eval_goals(create_level("boost")) == ("landing", "boost_cutoff")
    assert resolve_level_eval_goals(create_level("terminal")) == ("landing",)
    assert resolve_level_eval_goals(create_level("plunge")) == ("landing",)


def test_set_eval_goal_checked_rejects_unsupported_goal() -> None:
    class _Level:
        def supported_eval_goals(self) -> tuple[str, ...]:
            return ("landing",)

    with pytest.raises(ValueError, match="does not support eval goal 'boost_cutoff'"):
        set_eval_goal_checked(_Level(), "boost_cutoff")


def test_set_benchmark_mode_checked_calls_supported_level() -> None:
    class _Level:
        mode = None

        def set_benchmark_mode(self, mode: str) -> None:
            self.mode = mode

    level = _Level()
    set_benchmark_mode_checked(level, "sample")
    assert level.mode == "sample"


def test_list_batch_scenarios_safe_normalizes_strings() -> None:
    class _Level:
        def list_batch_scenarios(self) -> list[str]:
            return [" mid ", "", "steep", "   "]

    assert list_batch_scenarios_safe(_Level()) == ["mid", "steep"]


def test_scenario_has_randomized_fields_safe_supports_legacy_signature() -> None:
    class _LegacyLevel:
        def scenario_has_randomized_fields(self) -> bool:
            return True

    class _ModernLevel:
        def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
            return False

    assert scenario_has_randomized_fields_safe(_LegacyLevel(), "mid") is True
    assert scenario_has_randomized_fields_safe(_ModernLevel(), "mid") is False


def test_level_tag_helpers_apply_defaults() -> None:
    class _Level:
        pass

    level = _Level()
    assert level_plot_mode(level) == "none"
    assert level_plot_output(level) == "combined"
    assert level_plot_max_side_px(level) == 1800
    assert level_name_tag(level) == type(level).__module__.split(".")[-1]
    assert level_scenario_tag(level) == ""


def test_resolve_level_benchmark_profile_accepts_valid_profile() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="normal",
                scenarios=BenchmarkScenarioSets(
                    smoke=("mid",),
                    quick=("mid", "far"),
                    full=("near", "mid", "far"),
                ),
            )

    profile = resolve_level_benchmark_profile(_Level(), "demo")
    assert profile.policy == "normal"
    assert profile.scenarios.smoke == ("mid",)
    assert profile.scenarios.quick == ("mid", "far")
    assert profile.scenarios.full == ("near", "mid", "far")


def test_resolve_level_benchmark_profile_allows_excluded_with_empty_sets() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="excluded",
                scenarios=BenchmarkScenarioSets(smoke=(), quick=(), full=()),
            )

    profile = resolve_level_benchmark_profile(_Level(), "excluded_level")
    assert profile.policy == "excluded"
    assert profile.scenarios.full == ()


def test_resolve_level_benchmark_profile_requires_capability() -> None:
    class _Level:
        pass

    with pytest.raises(ValueError, match="does not implement benchmark_profile"):
        resolve_level_benchmark_profile(_Level(), "missing")


def test_resolve_level_benchmark_profile_rejects_invalid_policy() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="weird",  # type: ignore[arg-type]
                scenarios=BenchmarkScenarioSets(smoke=("mid",), quick=("mid",), full=("mid",)),
            )

    with pytest.raises(ValueError, match="invalid benchmark policy"):
        resolve_level_benchmark_profile(_Level(), "invalid")


def test_resolve_level_benchmark_profile_requires_non_empty_sets_for_normal() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="normal",
                scenarios=BenchmarkScenarioSets(smoke=(), quick=("mid",), full=("mid",)),
            )

    with pytest.raises(ValueError, match="must provide non-empty smoke/quick/full"):
        resolve_level_benchmark_profile(_Level(), "normal_empty")


def test_resolve_level_benchmark_profile_rejects_smoke_not_in_quick() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="observe_only",
                scenarios=BenchmarkScenarioSets(
                    smoke=("mid",),
                    quick=("far",),
                    full=("mid", "far"),
                ),
            )

    with pytest.raises(ValueError, match="smoke scenarios missing from quick"):
        resolve_level_benchmark_profile(_Level(), "bad_subset")


def test_resolve_level_benchmark_profile_rejects_quick_not_in_full() -> None:
    class _Level:
        def benchmark_profile(self) -> LevelBenchmarkProfile:
            return LevelBenchmarkProfile(
                policy="normal",
                scenarios=BenchmarkScenarioSets(
                    smoke=("mid",),
                    quick=("mid", "far"),
                    full=("mid",),
                ),
            )

    with pytest.raises(ValueError, match="quick scenarios missing from full"):
        resolve_level_benchmark_profile(_Level(), "bad_subset2")


def test_all_levels_expose_valid_benchmark_profile() -> None:
    for level_name in sorted(list_available_levels()):
        level = create_level(level_name)
        profile = resolve_level_benchmark_profile(level, level_name)
        assert profile.policy in {"normal", "observe_only", "excluded"}
