"""Configurable descent bot with multiple behavior profiles."""

from __future__ import annotations

from bots._descent_core import (
    BALANCED_POLICY,
    ECON_POLICY,
    SPEED_POLICY,
    DescentPolicy,
    StrategyDescentBot,
)
from core.bot import Bot


_BEHAVIOR_POLICIES: dict[str, DescentPolicy] = {
    "balanced": BALANCED_POLICY,
    "speed": SPEED_POLICY,
    "econ": ECON_POLICY,
}


class DescentBot(StrategyDescentBot):
    def __init__(self, behavior: str = "balanced") -> None:
        super().__init__(BALANCED_POLICY)
        self._behavior = "balanced"
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower().replace("-", "_")
        if key not in _BEHAVIOR_POLICIES:
            known = ", ".join(sorted(_BEHAVIOR_POLICIES))
            raise ValueError(f"Unknown descent behavior '{behavior}'. Expected one of: {known}")
        self._policy = _BEHAVIOR_POLICIES[key]
        self._behavior = key

    @property
    def behavior(self) -> str:
        return self._behavior


def create_bot() -> Bot:
    return DescentBot()


def list_behavior_names() -> tuple[str, ...]:
    return tuple(sorted(_BEHAVIOR_POLICIES))


__all__ = ["DescentBot", "create_bot", "list_behavior_names"]
