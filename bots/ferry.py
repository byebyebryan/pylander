"""Thin ferry bot wrapper over transfer setup/handoff core."""

from __future__ import annotations

from core.bot import Bot
from bots.transfer import TransferBot


class FerryBot(TransferBot):
    def __init__(self, behavior: str = "ferry") -> None:
        super().__init__(behavior=behavior)


def create_bot() -> Bot:
    return FerryBot()


def list_behavior_names() -> tuple[str, ...]:
    return ("ferry",)


__all__ = ["FerryBot", "create_bot", "list_behavior_names"]
