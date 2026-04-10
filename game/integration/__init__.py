"""Bot integration seam: game-code imports bot functionality through this module.

This module provides a stable integration point that keeps direct bot_framework
imports concentrated here rather than scattered through game code.
"""

from __future__ import annotations

from bot_framework.bot_actor_session import active_actor_bot
from bot_framework.bot_loop import update_bot_steps
from bot_framework.bot_profiler import BotLoopProfiler

__all__ = [
    "active_actor_bot",
    "update_bot_steps",
    "BotLoopProfiler",
]
