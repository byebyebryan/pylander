from __future__ import annotations


def __getattr__(name: str):
    if name == "LanderGame":
        from game.__main__ import LanderGame

        return LanderGame
    if name == "GameHost":
        from game.game_host import GameHost

        return GameHost
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LanderGame", "GameHost"]
