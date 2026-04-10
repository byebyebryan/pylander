"""Bot integration seam: game-code imports bot functionality through this module.

This module provides a stable integration point that keeps direct bot_framework
imports concentrated here rather than scattered through game code.

Imports from bot_framework are lazy - they only happen when the functions
are actually accessed, not at module load time. This inverts the dependency
by deferring bot_framework loads until needed.

The profiler interface is owned by game/runtime/profiler.py. This module
provides the concrete implementation factory.
"""

from __future__ import annotations

from game.runtime.profiler import BotProfiler


_LAZY_IMPORTS = {
    "active_actor_bot": (
        "bot_framework.bot_actor_session",
        "active_actor_bot",
    ),
    "attach_primary_bot": (
        "bot_framework.bot_actor_session",
        "attach_primary_bot",
    ),
    "install_world_actor_bots": (
        "bot_framework.bot_actor_session",
        "install_world_actor_bots",
    ),
    "update_bot_steps": (
        "bot_framework.bot_loop",
        "update_bot_steps",
    ),
    "BotLoopProfiler": (
        "bot_framework.bot_profiler",
        "BotLoopProfiler",
    ),
    "prime_boost_cutoff_for_primary_bot": (
        "bot_framework.eval.boost_cutoff",
        "prime_boost_cutoff_for_primary_bot",
    ),
    "print_headless_stats": (
        "bot_framework.eval.headless_stats",
        "print_headless_stats",
    ),
    "track_plot_events": (
        "bot_framework.eval.plot_events",
        "track_plot_events",
    ),
    "resolve_headless_bot_eval_decision": (
        "bot_framework.eval.result_pipeline",
        "resolve_headless_bot_eval_decision",
    ),
    "merge_bot_snapshots_into_result": (
        "bot_framework.eval.result_pipeline",
        "merge_bot_snapshots_into_result",
    ),
    "apply_bot_eval_to_result": (
        "bot_framework.eval.result_pipeline",
        "apply_bot_eval_to_result",
    ),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        from importlib import import_module

        module = import_module(module_path)
        return getattr(module, attr_name)
    if name == "create_bot_profiler":
        from bot_framework.bot_profiler import BotLoopProfiler

        def create_bot_profiler(
            *,
            headless: bool,
            enabled: bool | None = None,
            interval_s: float | None = None,
            log_lines: bool | None = None,
        ) -> BotProfiler:
            return BotLoopProfiler.from_settings(
                headless=headless,
                enabled=enabled,
                interval_s=interval_s,
                log_lines=log_lines,
            )

        return create_bot_profiler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
