from __future__ import annotations

from runtime.bootstrap import SystemsBundle, create_systems
from runtime.types import BotLoopContext
from runtime.loop_timing import LoopTimers
from runtime.run_metrics import RunMetricsTracker
from runtime.sensors import (
    build_headless_stats,
    build_sensors,
    build_vehicle_info,
    resolve_eval_target_pos,
)

__all__ = [
    "SystemsBundle",
    "create_systems",
    "LoopTimers",
    "BotLoopContext",
    "update_bot_steps",
    "RunMetricsTracker",
    "BotLoopProfiler",
    "resolve_eval_target_pos",
    "build_vehicle_info",
    "build_sensors",
    "build_headless_stats",
]


def __getattr__(name: str):
    if name == "update_bot_steps":
        from bot_framework.bot_loop import update_bot_steps

        return update_bot_steps
    if name == "BotLoopProfiler":
        from bot_framework.bot_profiler import BotLoopProfiler

        return BotLoopProfiler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
