"""Landers package with dynamic loader utilities.

- list_available_landers(): discover lander module names in this package
- load_lander_class(name): import module and find a subclass of lander.Lander
- create_lander(name): instantiate the discovered lander class
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from types import ModuleType
from typing import List, Type

from core.lander import Lander


def _package_path() -> str:
    return os.path.dirname(__file__)


def list_available_landers() -> List[str]:
    """Return available lander module names (filenames without extension)."""
    modules: List[str] = []
    for mod in pkgutil.iter_modules([_package_path()]):
        name = mod.name
        if name.startswith("_"):
            continue
        modules.append(name)
    modules.sort()
    return modules


def _find_lander_class_in_module(module: ModuleType) -> Type[Lander] | None:
    # If module provides an explicit factory, prefer that path
    factory = getattr(module, "create_lander", None)
    if callable(factory):
        instance = factory()
        if isinstance(instance, Lander):
            return type(instance)

    # Otherwise, search for a subclass of Lander defined in the module
    candidates: list[type] = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(cls, Lander)
            and cls is not Lander
            and cls.__module__ == module.__name__
        ):
            candidates.append(cls)

    if not candidates:
        return None

    # Prefer classes whose name ends with "Lander"
    preferred = [c for c in candidates if c.__name__.endswith("Lander")]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        preferred.sort(key=lambda c: c.__name__)
        return preferred[0]

    return candidates[0]


def load_lander_class(name: str) -> Type[Lander]:
    """Import `landers.<name>` and return the primary Lander subclass.

    Raises ImportError/ValueError on failure.
    """
    module_name = name.strip().lower().replace("-", "_")
    if not module_name or module_name.startswith("."):
        raise ValueError(f"Invalid lander name: {name!r}")

    module = importlib.import_module(f"landers.{module_name}")
    lander_cls = _find_lander_class_in_module(module)
    if lander_cls is None:
        raise ValueError(
            f"No Lander subclass found in module 'landers.{module_name}'"
        )
    return lander_cls


def create_lander(name: str) -> Lander:
    """Instantiate a lander by module name."""
    lander_cls = load_lander_class(name)
    return lander_cls()


__all__ = [
    "list_available_landers",
    "load_lander_class",
    "create_lander",
]



