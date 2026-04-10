"""Bot integration seam: game-code imports bot functionality through this module.

This module provides a stable integration point that keeps direct bot_framework
imports concentrated here rather than scattered through game code.

The profiler interface is owned by game/runtime/profiler.py. This module
provides the concrete implementation factory.
"""

from __future__ import annotations

from bot_framework.bot_actor_session import (
    active_actor_bot,
    attach_primary_bot,
    install_world_actor_bots,
)
from bot_framework.bot_loop import update_bot_steps
from bot_framework.bot_profiler import BotLoopProfiler
from bot_framework.eval.boost_cutoff import prime_boost_cutoff_for_primary_bot
from bot_framework.eval.headless_stats import print_headless_stats
from bot_framework.eval.plot_events import track_plot_events
from bot_framework.eval.result_pipeline import (
    apply_bot_eval_to_result,
    merge_bot_snapshots_into_result,
    resolve_headless_bot_eval_decision,
)

from game.runtime.profiler import BotProfiler


def create_bot_profiler(
    *,
    headless: bool,
    enabled: bool | None = None,
    interval_s: float | None = None,
    log_lines: bool | None = None,
) -> BotProfiler:
    """Factory to create a bot profiler instance.

    Returns a BotProfiler instance (concrete BotLoopProfiler) configured
    from settings or environment.
    """
    return BotLoopProfiler.from_settings(
        headless=headless,
        enabled=enabled,
        interval_s=interval_s,
        log_lines=log_lines,
    )


__all__ = [
    "active_actor_bot",
    "attach_primary_bot",
    "install_world_actor_bots",
    "update_bot_steps",
    "BotLoopProfiler",
    "prime_boost_cutoff_for_primary_bot",
    "track_plot_events",
    "print_headless_stats",
    "resolve_headless_bot_eval_decision",
    "merge_bot_snapshots_into_result",
    "apply_bot_eval_to_result",
    "create_bot_profiler",
]
