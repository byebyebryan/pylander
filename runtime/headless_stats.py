from __future__ import annotations

from typing import Any

from runtime.sensors import build_headless_stats


def print_headless_stats(
    *,
    elapsed_time: float,
    active_actor: Any,
    terrain: Any,
    actor_bots: dict[str, Any],
) -> None:
    parts = [f"t:{elapsed_time:6.2f}"]
    parts.append(build_headless_stats(active_actor, terrain))
    for uid, bot in actor_bots.items():
        if hasattr(bot, "get_headless_stats"):
            bot_str = bot.get_headless_stats()
            if bot_str:
                parts.append(f"{uid}:{bot_str}")
    print(" | ".join(parts))
