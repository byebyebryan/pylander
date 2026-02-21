from __future__ import annotations

from core.components import Engine, FuelTank, LanderState, Transform
from core.ecs import System


class StateTransitionSystem(System):
    """State transitions that are independent of contact resolution."""

    def update(self, dt: float) -> None:
        _ = dt
        if not self.world:
            return

        for entity in self.world.get_entities_with(LanderState, Engine, Transform, FuelTank):
            ls = entity.get_component(LanderState)
            eng = entity.get_component(Engine)
            trans = entity.get_component(Transform)
            tank = entity.get_component(FuelTank)
            if ls is None or eng is None or trans is None or tank is None:
                continue

            if ls.state == "landed" and eng.target_thrust > 0.0:
                ls.state = "flying"
                trans.pos.y += 1.0

            if ls.state == "flying" and tank.fuel <= 0.0 and eng.target_thrust <= 0.0:
                ls.state = "out_of_fuel"
