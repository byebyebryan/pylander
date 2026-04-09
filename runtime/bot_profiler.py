from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot_framework.bot_profiler import BotLoopProfiler, BotProfileCounter


def __getattr__(name: str):
    if name == "BotLoopProfiler":
        from bot_framework.bot_profiler import BotLoopProfiler

        return BotLoopProfiler
    if name == "BotProfileCounter":
        from bot_framework.bot_profiler import BotProfileCounter

        return BotProfileCounter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BotLoopProfiler", "BotProfileCounter"]
