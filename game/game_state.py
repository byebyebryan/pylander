"""Game state machine definitions for menu system."""

from __future__ import annotations

from enum import StrEnum


class GameState(StrEnum):
    """Top-level game states driven by GameHost."""

    TITLE = "title"
    PLAYING = "playing"
    PAUSED = "paused"


class PauseReason(StrEnum):
    """Why the game entered PAUSED state."""

    USER_REQUESTED = "user_requested"
    CRASHED = "crashed"
