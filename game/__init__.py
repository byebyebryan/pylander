from __future__ import annotations


def __getattr__(name: str):
    if name == "LanderGame":
        from game.__main__ import LanderGame

        return LanderGame
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LanderGame"]
