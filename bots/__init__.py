"""Bots package with dynamic loader utilities.

- list_available_bots(): discover bot module names in this package
- load_bot_class(name): import module and find a subclass of bot.Bot
- create_bot(name): instantiate the discovered bot class
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from types import ModuleType
from typing import List, Type

from bot import Bot


def _package_path() -> str:
    return os.path.dirname(__file__)


def list_available_bots() -> List[str]:
    """Return available bot module names (filenames without extension)."""
    modules: List[str] = []
    for mod in pkgutil.iter_modules([_package_path()]):
        name = mod.name
        if not name.startswith("_"):
            modules.append(name)
    modules.sort()
    return modules


def _find_bot_class_in_module(module: ModuleType) -> Type[Bot] | None:
    # If module provides an explicit factory, prefer that path
    factory = getattr(module, "create_bot", None)
    if callable(factory):
        instance = factory()
        if isinstance(instance, Bot):
            return type(instance)

    # Otherwise, search for a subclass of Bot defined in the module
    candidates: list[type] = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(cls, Bot)
            and cls is not Bot
            and cls.__module__ == module.__name__
        ):
            candidates.append(cls)

    if not candidates:
        return None

    # Prefer classes whose name ends with "Bot"
    preferred = [c for c in candidates if c.__name__.endswith("Bot")]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        # Arbitrarily pick the first in a stable order
        preferred.sort(key=lambda c: c.__name__)
        return preferred[0]

    # Fallback: first candidate sorted by name
    candidates.sort(key=lambda c: c.__name__)
    return candidates[0]


def load_bot_class(name: str) -> Type[Bot]:
    """Import `bots.<name>` and return the primary Bot subclass.

    Raises ImportError/ValueError on failure.
    """
    module_name = name.strip().lower().replace("-", "_")
    if not module_name or module_name.startswith("."):
        raise ValueError(f"Invalid bot name: {name!r}")

    module = importlib.import_module(f"bots.{module_name}")
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
