from __future__ import annotations

from typing import Type

from core.level import Level

_PUBLIC_LEVEL_ORDER: tuple[str, ...] = (
    "flat",
    "mountains",
    "boost",
    "terrain",
    "terminal",
    "plunge",
)
_LEGACY_LEVEL_REPLACEMENTS: dict[str, str] = {
    "boost_flat": "boost",
    "boost_downhill": "boost",
    "boost_climb": "boost",
    "terminal_normal": "terminal",
    "terminal_error": "terminal",
}


def list_public_levels() -> list[str]:
    return list(_PUBLIC_LEVEL_ORDER)


def list_available_levels() -> list[str]:
    return list_public_levels()


def is_public_level(level_name: str) -> bool:
    return str(level_name).strip().lower() in _PUBLIC_LEVEL_ORDER


def load_level_class(name: str) -> Type[Level]:
    key = str(name or "").strip().lower().replace("-", "_")
    if key in _LEGACY_LEVEL_REPLACEMENTS:
        replacement = _LEGACY_LEVEL_REPLACEMENTS[key]
        raise ValueError(
            f"Level '{name}' was removed; use '{replacement}' with canonical scenario paths"
        )
    factories = _level_classes()
    if key not in factories:
        known = ", ".join(_PUBLIC_LEVEL_ORDER)
        raise ValueError(f"Unknown level '{name}'. Expected one of: {known}")
    return factories[key]


def create_level(name: str) -> Level:
    return load_level_class(name)()


def _level_classes() -> dict[str, Type[Level]]:
    from levels.boost import BoostLevel
    from levels.flat import FlatLevel
    from levels.mountains import MountainsLevel
    from levels.plunge import PlungeLevel
    from levels.terrain import TerrainLevel
    from levels.terminal import TerminalLevel

    return {
        "flat": FlatLevel,
        "mountains": MountainsLevel,
        "boost": BoostLevel,
        "terrain": TerrainLevel,
        "terminal": TerminalLevel,
        "plunge": PlungeLevel,
    }
