from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import bots.pdg_terminal_gate as terminal_gate
from bots import create_bot
from bots.pdg_stages import FlightStage
from bots.pdg_terrain_divert import (
    TerrainDivertProbe,
    backstop_containment_override,
    evaluate_terrain_divert_probe,
)
from core.bot import (
    BotEnvironment,
    BotTarget,
    BotTerrainSummary,
    Sensors,
    TerrainBoundary,
)


class _RisingTerrain:
    def sample_height(self, x: float, lod: int = 0) -> float:
        _ = lod
        return 120.0 if float(x) >= 230.0 else 0.0

    def sample_slope(self, x: float, lod: int = 0) -> float:
        _ = x, lod
        return 0.0

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        step: float,
        lod: int = 0,
    ) -> list[tuple[float, float]]:
        _ = x0, x1, step, lod
        return []

    def resolution(self, lod: int = 0) -> float:
        _ = lod
        return 2.0


class _FlatTerrain:
    def sample_height(self, x: float, lod: int = 0) -> float:
        _ = x, lod
        return 0.0

    def sample_slope(self, x: float, lod: int = 0) -> float:
        _ = x, lod
        return 0.0

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        step: float,
        lod: int = 0,
    ) -> list[tuple[float, float]]:
        _ = x0, x1, step, lod
        return []

    def resolution(self, lod: int = 0) -> float:
        _ = lod
        return 2.0


def _bot() -> Any:
    bot = cast(Any, create_bot("pdg"))
    bot.vehicle_info = SimpleNamespace(height=20.0)
    return bot


def _sensors(*, x: float, y: float, vx: float, vy_up: float) -> Sensors:
    return Sensors(
        x=x,
        y=y,
        altitude=y,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=vx,
        vy_up=vy_up,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=1200.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )


def test_divert_probe_positive_clearance_on_flat_terrain() -> None:
    bot = _bot()
    bot.environment = BotEnvironment(
        terrain=_FlatTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=200.0, y=0.0, size=110.0),
        terrain_summary=BotTerrainSummary(
            target_ground_y=0.0,
            height_threshold=30.0,
        ),
        level_name="terrain",
        scenario_name="terrain:downhill:mid:clip:half",
    )

    probe = evaluate_terrain_divert_probe(
        bot,
        passive=_sensors(x=150.0, y=60.0, vx=70.0, vy_up=-5.0),
        projected_dx=-40.0,
        max_thrust_accel=22.0,
    )

    assert probe.active is False
    assert probe.mode is None


def test_divert_probe_reports_negative_margin_for_terrain_penetration() -> None:
    bot = _bot()
    bot.environment = BotEnvironment(
        terrain=_RisingTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=200.0, y=0.0, size=110.0),
        terrain_summary=BotTerrainSummary(
            target_ground_y=0.0,
            height_threshold=30.0,
            right_boundary=TerrainBoundary(
                direction=1,
                x=230.0,
                height=120.0,
                steepness=9.5,
                tail_steepness=0.0,
            ),
        ),
        level_name="terrain",
        scenario_name="terrain:flat:far:backstop:half",
    )

    probe = evaluate_terrain_divert_probe(
        bot,
        passive=_sensors(x=150.0, y=60.0, vx=70.0, vy_up=-5.0),
        projected_dx=-220.0,
        max_thrust_accel=22.0,
    )

    assert probe.active is True
    assert probe.mode == "lateral_containment"
    assert probe.min_margin is not None
    assert probe.min_margin < 0.0
    assert probe.first_limit_t is not None
    assert probe.worst_x is not None
    assert probe.worst_x >= 230.0
    assert probe.sample_count == 1


def test_divert_probe_ignores_rising_target_side_continuation() -> None:
    bot = _bot()
    bot.environment = BotEnvironment(
        terrain=_RisingTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=200.0, y=0.0, size=110.0),
        terrain_summary=BotTerrainSummary(
            target_ground_y=0.0,
            height_threshold=30.0,
            right_boundary=TerrainBoundary(
                direction=1,
                x=230.0,
                height=120.0,
                steepness=5.5,
                tail_steepness=2.5,
            ),
        ),
        level_name="boost",
        scenario_name="boost:climb:high:half",
    )

    probe = evaluate_terrain_divert_probe(
        bot,
        passive=_sensors(x=150.0, y=60.0, vx=70.0, vy_up=-5.0),
        projected_dx=-220.0,
        max_thrust_accel=22.0,
    )

    assert probe.active is False
    assert probe.mode is None


def test_terminal_gate_can_force_terrain_divert_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _bot()
    bot.environment = BotEnvironment(
        terrain=_RisingTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=200.0, y=0.0, size=110.0),
        terrain_summary=BotTerrainSummary(
            target_ground_y=0.0,
            height_threshold=30.0,
            right_boundary=TerrainBoundary(
                direction=1,
                x=230.0,
                height=120.0,
                steepness=9.5,
                tail_steepness=0.0,
            ),
        ),
        level_name="terrain",
        scenario_name="terrain:flat:far:backstop:half",
    )
    bot.state._active_stage = FlightStage.COAST

    monkeypatch.setattr(
        terminal_gate,
        "evaluate_terrain_divert_probe",
        lambda *args, **kwargs: TerrainDivertProbe(
            active=True,
            mode="lateral_containment",
            min_margin=-1.0,
            first_limit_t=1.25,
            worst_x=242.0,
            worst_y=24.0,
            horizon_s=3.0,
            sample_count=10,
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_latest_safe_state",
        lambda *args, **kwargs: terminal_gate.LatestSafeState(
            margin_s=0.75,
            best_candidate=terminal_gate.TerminalGateCandidate(
                burn_time_s=4.0,
                required_accel_ratio=0.42,
                upward_accel=1.0,
                tilt_feasible=True,
                ready=False,
            ),
        ),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_burn_time_candidates",
        lambda *args, **kwargs: ([4.0], 0.4, -8.0),
    )
    monkeypatch.setattr(
        terminal_gate,
        "_evaluate_candidate",
        lambda **kwargs: terminal_gate.TerminalGateCandidate(
            burn_time_s=float(kwargs["burn_time_s"]),
            required_accel_ratio=0.96,
            upward_accel=0.1,
            tilt_feasible=True,
            ready=False,
        ),
    )

    decision = terminal_gate.evaluate_terminal_gate(
        bot,
        dt=1.0 / 30.0,
        passive=_sensors(x=160.0, y=70.0, vx=60.0, vy_up=-8.0),
        dx=40.0,
        projected_dx=-40.0,
        dy=-70.0,
        alt=70.0,
        max_thrust_accel=22.0,
        min_thrust_accel=3.0,
        nominal_thrust_accel=18.0,
        thrust_ramp_up=2.0,
    )

    assert decision is not None
    assert decision.mode == "terrain_divert"
    assert bot.state._terminal_probe_count == 1
    assert bot.state._terrain_divert_mode == "lateral_containment"
    assert bot.state._terrain_divert_margin_min == pytest.approx(-1.0)
    assert bot.state._terrain_divert_first_limit_t == pytest.approx(1.25)
    assert bot.state._terrain_divert_worst_x == pytest.approx(242.0)


def test_containment_override_returns_inward_push() -> None:
    bot = _bot()
    bot.environment = BotEnvironment(
        terrain=_RisingTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=200.0, y=0.0, size=110.0),
        terrain_summary=BotTerrainSummary(
            target_ground_y=0.0,
            height_threshold=30.0,
            right_boundary=TerrainBoundary(
                direction=1,
                x=230.0,
                height=120.0,
                steepness=9.5,
                tail_steepness=0.0,
            ),
        ),
        level_name="terrain",
        scenario_name="terrain:flat:far:backstop:half",
    )
    override = backstop_containment_override(
        bot,
        passive=_sensors(x=150.0, y=60.0, vx=70.0, vy_up=-5.0),
        projected_dx=-80.0,
        max_thrust_accel=22.0,
    )

    assert override is not None
    ax, ay = override
    assert ax < 0.0
    assert ay > 9.8
