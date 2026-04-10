from __future__ import annotations

from game.core.components import Transform
from game.core.ecs import Entity
from game.core.maths import Vector2
from game.levels.common_world import PresetLevel


class _DynamicSiteLevel(PresetLevel):
    def _build_base_terrain(self, seed: int):
        raise NotImplementedError


def test_dynamic_site_update_caps_spawns_per_side_per_frame() -> None:
    level = _DynamicSiteLevel()
    level.world = object()  # type: ignore[assignment]
    level.dynamic_site_spawns_per_side_per_frame = 3
    level._dynamic_site_min_x = 0.0
    level._dynamic_site_max_x = 0.0

    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(0.0, 0.0)))

    calls: list[int] = []
    level._spawn_dynamic_site = (  # type: ignore[method-assign]
        lambda _game, *, direction: calls.append(direction)
    )

    class _Game:
        def get_active_actor(self):
            return actor

    level.update(_Game(), 1.0 / 60.0)

    assert calls == [1, 1, 1, -1, -1, -1]
