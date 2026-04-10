from __future__ import annotations

from dataclasses import dataclass

from game.levels.common_scenarios import SampleRange


TERMINAL_ANGLE_PROFILES: tuple[tuple[str, float], ...] = (
    ("shallower", 15.0),
    ("shallow", 30.0),
    ("mid", 45.0),
    ("steep", 60.0),
    ("steeper", 75.0),
)


@dataclass(frozen=True)
class TerminalScenario:
    name: str
    seed_key: str
    mode: str
    profile: str
    base_angle_deg: float
    cargo_mass: float
    radius: float | SampleRange
    angle_deviation_deg: float | SampleRange
    target_flight_time_s: float | SampleRange
    error_tier: str | None = None
    projected_dx_error: SampleRange | None = None


def terminal_normal_name(profile: str) -> str:
    return f"normal:{profile}"


def terminal_error_name(profile: str, tier: str) -> str:
    return f"error:{profile}:{tier}"


def _build_normal_scenario(profile: str, angle_deg: float) -> TerminalScenario:
    return TerminalScenario(
        name=terminal_normal_name(profile),
        seed_key=profile,
        mode="normal",
        profile=profile,
        base_angle_deg=float(angle_deg),
        cargo_mass=2250.0,
        radius=SampleRange(700.0, 900.0),
        angle_deviation_deg=SampleRange(-5.0, 5.0),
        target_flight_time_s=SampleRange(10.0, 12.0),
    )


@dataclass(frozen=True)
class _ErrorTier:
    key: str
    projected_dx_error: SampleRange


_ERROR_TIERS: tuple[_ErrorTier, ...] = (
    _ErrorTier(key="tight", projected_dx_error=SampleRange(30.0, 55.0)),
    _ErrorTier(key="wide", projected_dx_error=SampleRange(75.0, 110.0)),
)


def _build_error_scenario(
    profile: str, angle_deg: float, tier: _ErrorTier
) -> TerminalScenario:
    return TerminalScenario(
        name=terminal_error_name(profile, tier.key),
        seed_key=f"{profile}_{tier.key}",
        mode="error",
        profile=profile,
        base_angle_deg=float(angle_deg),
        cargo_mass=1800.0,
        radius=SampleRange(700.0, 900.0),
        angle_deviation_deg=SampleRange(-5.0, 5.0),
        target_flight_time_s=SampleRange(9.5, 12.5),
        error_tier=tier.key,
        projected_dx_error=tier.projected_dx_error,
    )


TERMINAL_SCENARIOS: tuple[TerminalScenario, ...] = tuple(
    [
        _build_normal_scenario(profile, angle_deg)
        for profile, angle_deg in TERMINAL_ANGLE_PROFILES
    ]
    + [
        _build_error_scenario(profile, angle_deg, tier)
        for profile, angle_deg in TERMINAL_ANGLE_PROFILES
        for tier in _ERROR_TIERS
    ]
)

TERMINAL_SCENARIO_BY_NAME = {scenario.name: scenario for scenario in TERMINAL_SCENARIOS}
TERMINAL_DEFAULT_SCENARIO = terminal_normal_name("mid")
TERMINAL_SMOKE_SCENARIOS: tuple[str, ...] = (
    terminal_normal_name("mid"),
    terminal_error_name("mid", "wide"),
)
TERMINAL_QUICK_SCENARIOS: tuple[str, ...] = (
    terminal_normal_name("shallow"),
    terminal_normal_name("mid"),
    terminal_normal_name("steep"),
    terminal_error_name("shallow", "tight"),
    terminal_error_name("mid", "wide"),
    terminal_error_name("steep", "wide"),
)
