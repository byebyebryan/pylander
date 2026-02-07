"""Hare bot implementation.

Currently aliases TurtleBot behavior until a dedicated controller is added.
"""

from __future__ import annotations

from .turtle import TurtleBot as HareBot
from core.bot import Bot, BotAction


def create_bot() -> Bot:
    return HareBot()


__all__ = ["HareBot", "create_bot"]
