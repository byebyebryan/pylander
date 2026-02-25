"""Dedicated flare bot built on coast guidance primitives."""

from __future__ import annotations

from bots.coast import CoastBot
from core.bot import Bot


class FlareBot(CoastBot):
    def __init__(self, behavior: str = "flare") -> None:
        super().__init__(behavior="coast")
        self.set_behavior(behavior)

    def set_behavior(self, behavior: str) -> None:
        key = str(behavior).strip().lower()
        if key not in {"flare", "coast"}:
            raise ValueError(f"Unknown flare behavior '{behavior}'. Expected one of: flare")
        super().set_behavior("coast")
        self._behavior = "flare"


def create_bot() -> Bot:
    return FlareBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("flare",)


__all__ = ["FlareBot", "create_bot", "list_behavior_names"]
