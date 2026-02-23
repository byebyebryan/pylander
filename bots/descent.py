"""Balanced descent bot (backward-compatible default)."""

from __future__ import annotations

from bots._descent_core import BALANCED_POLICY, StrategyDescentBot
from core.bot import Bot


class DescentBot(StrategyDescentBot):
    def __init__(self) -> None:
        super().__init__(BALANCED_POLICY)


def create_bot() -> Bot:
    return DescentBot()


__all__ = ["DescentBot", "create_bot"]
