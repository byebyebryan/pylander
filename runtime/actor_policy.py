"""Player actor selection policy."""

from __future__ import annotations

from core.components import PlayerControlled, PlayerSelectable
from core.ecs import Entity


def find_initial_player_actor_uid(actors: list[Entity]) -> str:
    for actor in actors:
        selected = actor.get_component(PlayerControlled)
        if selected is not None and selected.active:
            return actor.uid

    selectable: list[tuple[int, str]] = []
    for actor in actors:
        marker = actor.get_component(PlayerSelectable)
        if marker is not None:
            selectable.append((marker.order, actor.uid))
    if selectable:
        selectable.sort(key=lambda item: item[0])
        return selectable[0][1]

    return actors[0].uid
