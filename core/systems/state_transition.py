from __future__ import annotations

from core.components import Engine, FlightState, FuelTank, LanderGeometry, LanderState, Transform
from core.ecs import System

_MIN_TAKEOFF_CLEARANCE = 4.0


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

            if ls.state == FlightState.LANDED and eng.target_thrust > 0.0 and tank.fuel > 0.0:
                ls.state = FlightState.FLYING
                geo = entity.get_component(LanderGeometry)
                if geo is None:
                    takeoff_clearance = _MIN_TAKEOFF_CLEARANCE
                else:
                    takeoff_clearance = max(
                        _MIN_TAKEOFF_CLEARANCE,
                        (0.5 * float(geo.height)) + 1.0,
                    )
                trans.pos.y += takeoff_clearance

            if ls.state == FlightState.FLYING and tank.fuel <= 0.0:
                ls.state = FlightState.OUT_OF_FUEL
