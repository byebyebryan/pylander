from __future__ import annotations

from core.components import FuelTank, LanderState, Wallet


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def _get_focus_actor(game):
    if hasattr(game, "get_active_actor"):
        return game.get_active_actor()
    return game.lander


def should_end_default(
    game,
    *,
    stop_on_crash=False,
    stop_on_first_land=False,
    stop_on_out_of_fuel=False,
    max_time=None,
) -> bool:
    actor = _get_focus_actor(game)
    state = _require_component(actor, LanderState).state
    tank = _require_component(actor, FuelTank)
    if stop_on_crash and state == "crashed":
        return True
    if stop_on_first_land and state == "landed":
        return True
    if stop_on_out_of_fuel and tank.fuel <= 0.0:
        return True
    if (
        game.headless
        and max_time is not None
        and getattr(game, "_elapsed_time", 0.0) >= max_time
    ):
        return True
    return False


def compute_score_default(
    game,
    landing_count,
    crash_count,
    *,
    credits_score=1.0,
    fuel_score=10.0,
    landing_score=100.0,
    crash_penalty=-200.0,
) -> float:
    actor = _get_focus_actor(game)
    wallet = _require_component(actor, Wallet)
    tank = _require_component(actor, FuelTank)
    return (
        wallet.credits * credits_score
        + tank.fuel * fuel_score
        + landing_count * landing_score
        + crash_count * crash_penalty
    )
