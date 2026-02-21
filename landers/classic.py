from __future__ import annotations

from core.lander import Lander


class ClassicLander(Lander):
    """Default lander profile."""


def create_lander() -> Lander:
    return ClassicLander()
