from __future__ import annotations

from utils.protocols import ControlTuple
from core.components import ControlIntent, Engine
from core.ecs import System


class ControlRoutingSystem(System):
    """Route selected player/bot controls into engine targets."""

    def __init__(self):
        super().__init__()
        self._pending_controls: dict[str, ControlTuple] = {}
        self._broadcast_controls: ControlTuple = (None, None, False)

    def set_controls(self, controls: ControlTuple | None, actor_uid: str | None = None) -> None:
        normalized = controls if controls is not None else (None, None, False)
        if actor_uid is None:
            self._broadcast_controls = normalized
            return
        self._pending_controls[actor_uid] = normalized

    def set_controls_map(self, controls_by_uid: dict[str, ControlTuple | None]) -> None:
        self._pending_controls = {
            uid: (controls if controls is not None else (None, None, False))
            for uid, controls in controls_by_uid.items()
        }
        self._broadcast_controls = (None, None, False)

    def update(self, dt: float) -> None:
        _ = dt
        if not self.world:
            return
        for entity in self.world.get_entities_with(ControlIntent, Engine):
            target_thrust, target_angle, refuel = self._pending_controls.get(
                entity.uid, self._broadcast_controls
            )
            intent = entity.get_component(ControlIntent)
            engine = entity.get_component(Engine)
            if intent is None or engine is None:
                continue

            intent.target_thrust = target_thrust
            intent.target_angle = target_angle
            intent.refuel_requested = bool(refuel)

            if target_thrust is not None:
                engine.target_thrust = max(0.0, min(1.0, target_thrust))
            if target_angle is not None:
                engine.target_angle = target_angle
        self._pending_controls.clear()
        self._broadcast_controls = (None, None, False)
