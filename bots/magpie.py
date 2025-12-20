"""Magpie bot implementation.

Currently aliases TurtleBot behavior until a dedicated controller is added.
"""

from __future__ import annotations

from .turtle import TurtleBot as MagpieBot
from bot import Bot


def create_bot() -> Bot:
    return MagpieBot()


__all__ = ["MagpieBot", "create_bot"]
