from __future__ import annotations

from game.levels.registry import is_public_level
from bot_framework.scenarios import ScenarioBinding
from bot_framework.scenarios import (
    create_scenario_level,
    resolve_scenario_binding as resolve_selector_binding,
)


def _resolve_runtime_binding(
    level_name: str,
    scenario_path: tuple[str, ...] | list[str] | None = None,
) -> ScenarioBinding:
    if is_public_level(level_name):
        normalized = str(level_name).strip().lower()
        return ScenarioBinding(
            level_name=normalized,
            path=(),
            runtime_level_name=normalized,
            runtime_scenario_name=None,
        )
    return resolve_selector_binding(level_name, scenario_path)


def create_level_checked(level_name: str):
    if is_public_level(level_name):
        from game.levels import create_level as create_gameplay_level

        try:
            return create_gameplay_level(level_name)
        except ImportError as exc:
            raise ValueError(f"Failed to load level '{level_name}': {exc}") from exc
        except ValueError as exc:
            message = str(exc)
            if "Unknown level" in message or "was removed" in message:
                raise ValueError(f"Failed to load level '{level_name}': {exc}") from exc
            raise ValueError(
                f"Level '{level_name}' failed to initialize: {exc}"
            ) from exc
    try:
        return create_scenario_level(level_name)
    except ImportError as exc:
        raise ValueError(
            f"Failed to load scenario level '{level_name}': {exc}"
        ) from exc
    except ValueError as exc:
        message = str(exc)
        if "Unknown scenario root" in message:
            raise ValueError(
                f"Failed to load scenario level '{level_name}': {exc}"
            ) from exc
        raise ValueError(
            f"Scenario level '{level_name}' failed to initialize: {exc}"
        ) from exc
