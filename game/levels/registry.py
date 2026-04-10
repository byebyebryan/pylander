from __future__ import annotations

from typing import Type

from game.core.level import Level

_PUBLIC_GAMEPLAY_LEVELS: tuple[str, ...] = (
    "flat",
    "mountains",
)


def list_public_levels() -> list[str]:
    return list(_PUBLIC_GAMEPLAY_LEVELS)


def list_available_levels() -> list[str]:
    return list(_PUBLIC_GAMEPLAY_LEVELS)


def is_public_level(level_name: str) -> bool:
    return str(level_name).strip().lower() in _PUBLIC_GAMEPLAY_LEVELS


def load_level_class(name: str) -> Type[Level]:
    key = str(name or "").strip().lower().replace("-", "_")
    factories = _level_classes()
    if key not in factories:
        known = ", ".join(_PUBLIC_GAMEPLAY_LEVELS)
        raise ValueError(f"Unknown gameplay level '{name}'. Expected one of: {known}")
    return factories[key]


def create_level(name: str) -> Level:
    return load_level_class(name)()


def _level_classes() -> dict[str, Type[Level]]:
    from game.levels.flat import FlatLevel
    from game.levels.mountains import MountainsLevel

    return {
        "flat": FlatLevel,
        "mountains": MountainsLevel,
    }
