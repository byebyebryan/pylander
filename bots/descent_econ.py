"""Fuel-aware descent strategy prioritizing efficiency."""

from __future__ import annotations

from bots._descent_core import ECON_POLICY, StrategyDescentBot
from core.bot import Bot


class DescentEconBot(StrategyDescentBot):
    def __init__(self) -> None:
        super().__init__(ECON_POLICY)


def create_bot() -> Bot:
    return DescentEconBot()


__all__ = ["DescentEconBot", "create_bot"]
