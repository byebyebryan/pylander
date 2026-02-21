from __future__ import annotations

from core.components import LanderGeometry
from core.lander import Lander
from core.maths import Vector2


class SimpleLander(Lander):
    """Tall-body variant using the standard ECS control pipeline."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        geo = self.get_component(LanderGeometry)
        if geo is None:
            raise RuntimeError("Lander missing LanderGeometry component")
        geo.width = 8.0
        geo.height = 10.0
        geo.polygon_points = [
            Vector2(-geo.width / 2.0, -geo.height / 2.0),
            Vector2(geo.width / 2.0, -geo.height / 2.0),
            Vector2(geo.width / 2.0, geo.height / 2.0),
            Vector2(-geo.width / 2.0, geo.height / 2.0),
        ]


def create_lander() -> Lander:
    return SimpleLander()
