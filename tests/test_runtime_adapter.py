"""Tests for runtime_adapter."""

from __future__ import annotations

import pytest

from runtime.runtime_adapter import (
    FullBotRuntimeAdapter,
    NoBotRuntimeAdapter,
    build_noop_eval_hooks,
    make_runtime_adapter,
)


def test_build_noop_eval_hooks_returns_valid_hooks():
    hooks = build_noop_eval_hooks()
    assert callable(hooks.prime_boost_cutoff_for_primary_bot)
    assert callable(hooks.track_plot_events)
    assert callable(hooks.print_headless_stats)
    assert callable(hooks.resolve_headless_bot_eval_decision)
    assert callable(hooks.merge_bot_snapshots_into_result)
    assert callable(hooks.apply_bot_eval_to_result)


def test_make_runtime_adapter_returns_nobot_when_no_bot():
    adapter = make_runtime_adapter(bot=None, headless=False)
    assert isinstance(adapter, NoBotRuntimeAdapter)
    assert not isinstance(adapter, FullBotRuntimeAdapter)


def test_make_runtime_adapter_returns_full_when_bot_provided():
    from bots import create_bot

    bot = create_bot("pdg")
    adapter = make_runtime_adapter(bot=bot, headless=False)
    assert isinstance(adapter, FullBotRuntimeAdapter)
    assert not isinstance(adapter, NoBotRuntimeAdapter)


def test_make_runtime_adapter_raises_when_headless_without_bot():
    with pytest.raises(ValueError, match="Headless mode requires a bot"):
        make_runtime_adapter(bot=None, headless=True)


def test_noop_apply_bot_eval_to_result_sets_expected_fields():
    hooks = build_noop_eval_hooks()
    result = {}
    hooks.apply_bot_eval_to_result(result=result, eval_goal="landing")
    assert result["eval_goal"] == "landing"
    assert result["eval_early_end"] is False


def test_noop_resolve_headless_bot_eval_decision_returns_none():
    hooks = build_noop_eval_hooks()
    decision = hooks.resolve_headless_bot_eval_decision(headless=True, bot=None)
    assert decision is None
