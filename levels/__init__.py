"""Levels package with dynamic loader utilities.

- list_available_levels(): discover level module names in this package
- load_level_class(name): import module and find a subclass of level.Level
- create_level(name): instantiate the discovered level class
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from types import ModuleType
from typing import List, Type

from core.level import Level


def _package_path() -> str:
    return os.path.dirname(__file__)


def list_available_levels() -> List[str]:
    """Return available level module names (filenames without extension)."""
    modules: List[str] = []
    for mod in pkgutil.iter_modules([_package_path()]):
        name = mod.name
        if name.startswith("level_"):
            modules.append(name)
    modules.sort()
    return modules


def _find_level_class_in_module(module: ModuleType) -> Type[Level] | None:
    # If module provides an explicit factory, prefer that path
    factory = getattr(module, "create_level", None)
    if callable(factory):
        instance = factory()
        if isinstance(instance, Level):
            return type(instance)

    # Otherwise, search for a subclass of Level defined in the module
    candidates: list[type] = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(cls, Level)
            and cls is not Level
            and cls.__module__ == module.__name__
        ):
            candidates.append(cls)

    if not candidates:
        return None

    # Prefer classes whose name ends with "Level"
    preferred = [c for c in candidates if c.__name__.endswith("Level")]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        preferred.sort(key=lambda c: c.__name__)
        return preferred[0]

    candidates.sort(key=lambda c: c.__name__)
    return candidates[0]


def load_level_class(name: str) -> Type[Level]:
    """
    Load Level subclass by module name (e.g., "level_1").
    Raises ImportError/ValueError on failure.
    """
    module_name = name.strip().lower().replace("-", "_")
    if not module_name or module_name.startswith("."):
        raise ValueError(f"Invalid level name: {name!r}")

    module = importlib.import_module(f"levels.{module_name}")
    level_cls = _find_level_class_in_module(module)
    if level_cls is None:
        raise ValueError(f"No Level subclass found in module 'levels.{module_name}'")
    return level_cls


def create_level(name: str) -> Level:
    """Instantiate a level by module name."""
    level_cls = load_level_class(name)
    return level_cls()


__all__ = [
    "list_available_levels",
    "load_level_class",
    "create_level",
]
