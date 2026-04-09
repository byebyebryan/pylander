from __future__ import annotations

import logging
from typing import Any, Type

from core.bot import Bot

_PUBLIC_BOT_ORDER: tuple[str, ...] = ("pdg", "plunge")
_BOT_SPECS: tuple[tuple[str, str], ...] = (
    ("pdg", "bots.pdg::PDGBot"),
    ("plunge", "bots.plunge::PlungeBot"),
)

_logger = logging.getLogger(__name__)


def list_available_bots() -> list[str]:
    available, _unavailable = _bot_classes()
    return [name for name in _PUBLIC_BOT_ORDER if name in available]


def load_bot_class(name: str) -> Type[Bot]:
    key = str(name or "").strip().lower().replace("-", "_")
    factories, unavailable = _bot_classes()
    if key not in factories:
        if key in unavailable:
            raise ValueError(
                f"Bot '{name}' is unavailable: {unavailable[key]}. "
                "Install optional bot dependencies with 'uv sync --extra bot'."
            )
        known = ", ".join(_PUBLIC_BOT_ORDER)
        raise ValueError(f"Unknown bot '{name}'. Expected one of: {known}")
    return factories[key]


def create_bot(name: str, *, config_override: dict[str, Any] | None = None) -> Bot:
    bot_cls = load_bot_class(name)
    try:
        bot = bot_cls()
    except (ImportError, ModuleNotFoundError) as exc:
        raise ValueError(
            f"Bot '{name}' failed to initialize: {exc}. "
            "Install optional bot dependencies with 'uv sync --extra bot'."
        ) from exc
    if config_override:
        apply_override = getattr(bot, "apply_config_override", None)
        if not callable(apply_override):
            raise ValueError(f"Bot '{name}' does not support --bot-config overrides")
        apply_override(dict(config_override))
    return bot


def _bot_classes() -> tuple[dict[str, Type[Bot]], dict[str, str]]:
    result: dict[str, Type[Bot]] = {}
    unavailable: dict[str, str] = {}

    for key, spec in _BOT_SPECS:
        try:
            module_path, class_name = spec.split("::")
            from importlib import import_module

            module = import_module(module_path)
            bot_cls = getattr(module, class_name)
            result[key] = bot_cls
        except Exception as exc:  # noqa: BLE001
            unavailable[key] = str(exc)
            _logger.debug(
                "Skipping bot '%s' (failed to load: %s). "
                "Install optional bot dependencies for full bot support.",
                key,
                exc,
            )

    if not result:
        _logger.warning(
            "No bots available. Install optional bot dependencies: uv sync --extra bot"
        )

    return result, unavailable
