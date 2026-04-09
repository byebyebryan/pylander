from __future__ import annotations


def __getattr__(name: str):
    if name == "update_bot_steps":
        from bot_framework.bot_loop import update_bot_steps

        return update_bot_steps
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
