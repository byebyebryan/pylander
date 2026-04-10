from __future__ import annotations

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
