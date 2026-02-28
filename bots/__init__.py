"""Bots package with dynamic loader utilities.

- list_available_bots(): discover bot module names in this package
- load_bot_class(name): import module and find a subclass of bot.Bot
- create_bot(name): instantiate the discovered bot class
"""

from __future__ import annotations

from typing import List, Type

from core.bot import Bot
from core.plugin_loader import (
    find_primary_subclass,
    import_named_module,
    list_modules,
    package_path,
)


def _package_path() -> str:
    return package_path(__file__)


def list_available_bots() -> List[str]:
    """Return available bot module names (filenames without extension)."""
    return list_modules(_package_path())


def _find_bot_class_in_module(module) -> Type[Bot] | None:
    return find_primary_subclass(
        module,
        base_type=Bot,
        preferred_suffix="Bot",
        explicit_factory_name="create_bot",
    )


def load_bot_class(name: str) -> Type[Bot]:
    """Import `bots.<name>` and return the primary Bot subclass.

    Raises ImportError/ValueError on failure.
    """
    module = import_named_module("bots", name)
    module_name = module.__name__.split(".", 1)[-1]
    bot_cls = _find_bot_class_in_module(module)
    if bot_cls is None:
        raise ValueError(f"No Bot subclass found in module 'bots.{module_name}'")
    return bot_cls


def create_bot(name: str) -> Bot:
    """Instantiate a bot by module name."""
    bot_cls = load_bot_class(name)
    return bot_cls()


__all__ = [
    "list_available_bots",
    "load_bot_class",
    "create_bot",
]
