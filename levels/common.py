from __future__ import annotations


def should_end_default(
    game,
    *,
    stop_on_crash=False,
    stop_on_first_land=False,
    stop_on_out_of_fuel=False,
    max_time=None,
) -> bool:
    state = game.lander.state
    if stop_on_crash and state == "crashed":
        return True
    if stop_on_first_land and state == "landed":
        return True
    if stop_on_out_of_fuel and getattr(game.lander, "fuel", 0.0) <= 0.0:
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
    return (
        game.lander.credits * credits_score
        + game.lander.fuel * fuel_score
        + landing_count * landing_score
        + crash_count * crash_penalty
    )
