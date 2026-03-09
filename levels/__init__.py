"""Levels package with dynamic loader utilities.

- list_available_levels(): discover level module names in this package
- load_level_class(name): import module and find a subclass of level.Level
- create_level(name): instantiate the discovered level class
"""

from __future__ import annotations

from typing import List, Type

from core.level import Level
from core.plugin_loader import (
    find_primary_subclass,
    import_named_module,
    list_modules,
    package_path,
)


def _package_path() -> str:
    return package_path(__file__)


def list_available_levels() -> List[str]:
    """Return available level module names (filenames without extension)."""
    return list_modules(_package_path(), excluded={"common", "scenario_common", "setup_base", "staged_eval"})


def _find_level_class_in_module(module) -> Type[Level] | None:
    return find_primary_subclass(
        module,
        base_type=Level,
        preferred_suffix="Level",
        explicit_factory_name="create_level",
    )


def load_level_class(name: str) -> Type[Level]:
    """
    Load Level subclass by module name (e.g., "flat").
    Raises ImportError/ValueError on failure.
    """
    module = import_named_module("levels", name)
    module_name = module.__name__.split(".", 1)[-1]
    cls = _find_level_class_in_module(module)
    if cls is None:
        raise ValueError(f"No Level subclass found in module 'levels.{module_name}'")
    return cls


def create_level(name: str) -> Level:
    """Instantiate a level by module name."""
    cls = load_level_class(name)
    return cls()


__all__ = [
    "list_available_levels",
    "load_level_class",
    "create_level",
]
