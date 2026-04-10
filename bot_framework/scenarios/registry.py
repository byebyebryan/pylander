from __future__ import annotations

from typing import Type

from game.core.level import Level

_PUBLIC_SCENARIO_ROOTS: tuple[str, ...] = (
    "boost",
    "terrain",
    "terminal",
    "plunge",
)


def list_public_scenario_roots() -> list[str]:
    return list(_PUBLIC_SCENARIO_ROOTS)


def is_public_scenario_root(level_name: str) -> bool:
    return str(level_name).strip().lower() in _PUBLIC_SCENARIO_ROOTS


def list_available_scenarios() -> list[str]:
    return list(_PUBLIC_SCENARIO_ROOTS)


def load_scenario_class(name: str) -> Type[Level]:
    key = str(name or "").strip().lower().replace("-", "_")
    factories = _scenario_classes()
    if key not in factories:
        known = ", ".join(_PUBLIC_SCENARIO_ROOTS)
        raise ValueError(f"Unknown scenario root '{name}'. Expected one of: {known}")
    return factories[key]


def create_scenario_level(name: str) -> Level:
    return load_scenario_class(name)()


def _scenario_classes() -> dict[str, Type[Level]]:
    from bot_framework.scenarios.boost import BoostLevel
    from bot_framework.scenarios.plunge import PlungeLevel
    from bot_framework.scenarios.terrain import TerrainLevel
    from bot_framework.scenarios.terminal import TerminalLevel

    return {
        "boost": BoostLevel,
        "terrain": TerrainLevel,
        "terminal": TerminalLevel,
        "plunge": PlungeLevel,
    }
