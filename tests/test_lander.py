from __future__ import annotations

import pytest

from core.components import CargoHold, Engine, FuelTank, PhysicsState
from core.lander import Lander


def test_default_lander_profile_matches_rebalanced_vehicle_budget() -> None:
    lander = Lander()

    physics = lander.get_component(PhysicsState)
    tank = lander.get_component(FuelTank)
    cargo = lander.get_component(CargoHold)
    engine = lander.get_component(Engine)

    assert physics is not None
    assert tank is not None
    assert cargo is not None
    assert engine is not None

    full_fuel_mass = tank.max_fuel * tank.density
    full_load_mass = physics.mass + full_fuel_mass + cargo.max_cargo_mass
    nominal_twr = engine.max_power / (full_load_mass * 9.8)

    assert physics.mass == pytest.approx(7200.0)
    assert tank.fuel == pytest.approx(140.0)
    assert tank.max_fuel == pytest.approx(140.0)
    assert tank.density == pytest.approx(45.0)
    assert cargo.max_cargo_mass == pytest.approx(6000.0)
    assert full_fuel_mass == pytest.approx(6300.0)
    assert full_fuel_mass / cargo.max_cargo_mass == pytest.approx(1.05)
    assert full_load_mass == pytest.approx(19500.0)
    assert nominal_twr == pytest.approx(240000.0 / (19500.0 * 9.8))
    assert engine.max_power == pytest.approx(240000.0)
    assert engine.overdrive_burn_multiplier == pytest.approx(8.0)
