from __future__ import annotations

import pytest

from core.level_capabilities import (
    level_name_tag,
    level_plot_mode,
    level_scenario_tag,
    list_batch_scenarios_safe,
    resolve_default_bot_name,
    scenario_has_randomized_fields_safe,
    set_benchmark_mode_checked,
    set_eval_mode_checked,
    set_eval_scenario_checked,
)


def test_resolve_default_bot_name_normalizes_whitespace() -> None:
    class _Level:
        default_bot_name = "  zem_zev  "

    assert resolve_default_bot_name(_Level()) == "zem_zev"


def test_set_eval_scenario_checked_requires_capability() -> None:
    class _NoScenario:
        pass

    with pytest.raises(ValueError, match="does not support scenario selection"):
        set_eval_scenario_checked(_NoScenario(), "mid")


def test_set_eval_mode_checked_respects_auto_fallback() -> None:
    class _NoEvalMode:
        pass

    set_eval_mode_checked(_NoEvalMode(), "auto")
    with pytest.raises(ValueError, match="does not support --eval-mode"):
        set_eval_mode_checked(_NoEvalMode(), "focused")


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
    assert level_name_tag(level) == type(level).__module__.split(".")[-1]
    assert level_scenario_tag(level) == ""
