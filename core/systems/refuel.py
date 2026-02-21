from __future__ import annotations

from core.components import (
    ControlIntent,
    FuelTank,
    LanderGeometry,
    LanderState,
    RefuelConfig,
    Transform,
    Wallet,
)
from core.ecs import System
from core.maths import Range1D


class RefuelSystem(System):
    """Handle landed refuel transactions against nearby target platforms."""

    def __init__(self, targets):
        super().__init__()
        self.targets = targets

    def update(self, dt: float) -> None:
        if not self.world or self.targets is None:
            return

        for entity in self.world.get_entities_with(
            LanderState,
            FuelTank,
            Wallet,
            Transform,
            LanderGeometry,
            RefuelConfig,
            ControlIntent,
        ):
            self._update_entity(entity, dt)

    def _update_entity(self, entity, dt: float) -> None:
        ls = entity.get_component(LanderState)
        tank = entity.get_component(FuelTank)
        wallet = entity.get_component(Wallet)
        trans = entity.get_component(Transform)
        geo = entity.get_component(LanderGeometry)
        cfg = entity.get_component(RefuelConfig)
        intent = entity.get_component(ControlIntent)
        if None in (ls, tank, wallet, trans, geo, cfg, intent):
            return
        if ls.state != "landed" or not intent.refuel_requested or tank.fuel >= tank.max_fuel:
            return

        nearby = self.targets.get_targets(Range1D.from_center(trans.pos.x, geo.width))
        if not nearby:
            return
        target = nearby[0]
        price = target.info.get("fuel_price", 10.0) if getattr(target, "info", None) else 10.0

        fuel_needed = tank.max_fuel - tank.fuel
        max_by_time = cfg.refuel_rate * dt
        if price > 0:
            max_by_credits = max(0.0, wallet.credits) / price
        else:
            max_by_credits = float("inf")
        fuel_to_add = min(fuel_needed, max_by_time, max_by_credits)
        if fuel_to_add <= 0:
            return
        tank.fuel += fuel_to_add
        spent = fuel_to_add * max(0.0, price)
        wallet.credits = max(0.0, wallet.credits - spent)
