from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from types import ModuleType
from typing import TypeVar

T = TypeVar("T")


def package_path(file_path: str) -> str:
    return os.path.dirname(file_path)


def list_modules(pkg_path: str, *, excluded: set[str] | None = None) -> list[str]:
    blocked = excluded or set()
    modules: list[str] = []
    for mod in pkgutil.iter_modules([pkg_path]):
        name = mod.name
        if name.startswith("_") or name in blocked:
            continue
        modules.append(name)
    modules.sort()
    return modules


def import_named_module(package_name: str, name: str) -> ModuleType:
    module_name = name.strip().lower().replace("-", "_")
    if not module_name or module_name.startswith("."):
        raise ValueError(f"Invalid module name: {name!r}")
    return importlib.import_module(f"{package_name}.{module_name}")


def find_primary_subclass(
    module: ModuleType,
    *,
    base_type: type[T],
    preferred_suffix: str,
    explicit_factory_name: str,
) -> type[T] | None:
    factory = getattr(module, explicit_factory_name, None)
    if callable(factory):
        instance = factory()
        if isinstance(instance, base_type):
            return type(instance)

    candidates: list[type[T]] = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(cls, base_type)
            and cls is not base_type
            and cls.__module__ == module.__name__
        ):
            candidates.append(cls)

    if not candidates:
        return None

    preferred = [c for c in candidates if c.__name__.endswith(preferred_suffix)]
    pool = preferred if preferred else candidates
    pool.sort(key=lambda c: c.__name__)
    return pool[0]
