"""Thin ECS lander entity."""

from __future__ import annotations

from game.core.components import (
    ActorControlRole,
    ActorProfile,
    CargoHold,
    ControlIntent,
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    PlayerSelectable,
    PhysicsState,
    Radar,
    RefuelConfig,
    SensorReadings,
    Transform,
    Wallet,
)
from game.core.ecs import Entity
from game.core.maths import Vector2


class Lander(Entity):
    """Entity that only composes lander-related components."""

    def __init__(self, start_pos: Vector2 | None = None):
        super().__init__()
        spawn_pos = Vector2(start_pos) if start_pos is not None else Vector2(100.0, 0.0)
        self.start_pos = Vector2(spawn_pos)

        self.add_component(Transform(pos=Vector2(spawn_pos)))
        self.add_component(PhysicsState())
        self.add_component(FuelTank())
        self.add_component(CargoHold())
        self.add_component(Engine())
        self.add_component(LanderGeometry())
        self.add_component(Radar())
        self.add_component(LanderState())
        self.add_component(Wallet())
        self.add_component(ActorProfile(kind="lander"))
        self.add_component(ActorControlRole(role="none"))
        self.add_component(PlayerSelectable())
        self.add_component(ControlIntent())
        self.add_component(RefuelConfig())
        self.add_component(SensorReadings())
