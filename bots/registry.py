from __future__ import annotations

from typing import Any, Type

from core.bot import Bot

_PUBLIC_BOT_ORDER: tuple[str, ...] = ("pdg", "plunge")


def list_available_bots() -> list[str]:
    return list(_PUBLIC_BOT_ORDER)


def load_bot_class(name: str) -> Type[Bot]:
    key = str(name or "").strip().lower().replace("-", "_")
    factories = _bot_classes()
    if key not in factories:
        known = ", ".join(_PUBLIC_BOT_ORDER)
        raise ValueError(f"Unknown bot '{name}'. Expected one of: {known}")
    return factories[key]


def create_bot(name: str, *, config_override: dict[str, Any] | None = None) -> Bot:
    bot_cls = load_bot_class(name)
    bot = bot_cls()
    if config_override:
        apply_override = getattr(bot, "apply_config_override", None)
        if not callable(apply_override):
            raise ValueError(f"Bot '{name}' does not support --bot-config overrides")
        apply_override(dict(config_override))
    return bot


def _bot_classes() -> dict[str, Type[Bot]]:
    from bots.pdg import PDGBot
    from bots.plunge import PlungeBot

    return {
        "pdg": PDGBot,
        "plunge": PlungeBot,
    }
