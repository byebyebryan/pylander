from __future__ import annotations

from core.components import LanderGeometry
from core.lander import Lander


class DifferentialLander(Lander):
    """Wide-hull variant using the standard ECS control pipeline."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        geo = self.get_component(LanderGeometry)
        if geo is None:
            raise RuntimeError("Lander missing LanderGeometry component")
        geo.width = 10.0
        geo.height = 7.0


def create_lander() -> Lander:
    return DifferentialLander()
