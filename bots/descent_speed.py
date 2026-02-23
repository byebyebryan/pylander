"""Aggressive descent strategy prioritizing speed."""

from __future__ import annotations

from bots._descent_core import SPEED_POLICY, StrategyDescentBot
from core.bot import Bot


class DescentSpeedBot(StrategyDescentBot):
    def __init__(self) -> None:
        super().__init__(SPEED_POLICY)


def create_bot() -> Bot:
    return DescentSpeedBot()


__all__ = ["DescentSpeedBot", "create_bot"]
