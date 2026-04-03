from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from dataclasses import replace

from bots import create_bot
from bots.pdg_boost_clearance import (
    apply_boost_clearance_guard,
    evaluate_boost_clearance_probe,
)
from core.bot import BotAction, BotEnvironment, BotTarget, Sensors


class _SourceRiseTerrain:
    def sample_height(self, x: float, lod: int = 0) -> float:
        _ = lod
        xx = float(x)
        if xx < 85.0:
            return 0.0
        if xx < 110.0:
            return (xx - 85.0) * 3.2
        if xx < 160.0:
            return 80.0
        if xx < 230.0:
            return max(0.0, 80.0 - ((xx - 160.0) * 1.142857142857143))
        return 0.0

    def sample_slope(self, x: float, lod: int = 0) -> float:
        _ = lod
        xx = float(x)
        if xx < 85.0:
            return 0.0
        if xx < 110.0:
            return 3.2
        if xx < 160.0:
            return 0.0
        if xx < 230.0:
            return -1.142857142857143
        return 0.0

    def profile(
        self,
        x0: float,
        x1: float,
        *,
        step: float,
        lod: int = 0,
    ) -> list[tuple[float, float]]:
        _ = lod
        out: list[tuple[float, float]] = []
        x = float(x0)
        while x <= float(x1):
            out.append((x, self.sample_height(x)))
            x += max(1.0, float(step))
        return out

    def resolution(self, lod: int = 0) -> float:
        _ = lod
        return 2.0


def _bot() -> Any:
    bot = cast(Any, create_bot("pdg"))
    bot.vehicle_info = SimpleNamespace(height=20.0)
    bot.environment = BotEnvironment(
        terrain=_SourceRiseTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=800.0, y=0.0, size=110.0),
        level_name="terrain",
        scenario_name="terrain:reactive:boost_clearance",
        scenario_params={
            "hazard_driver": "progress_clearance",
            "obstacle_support_x0": 85.0,
            "obstacle_support_x1": 230.0,
        },
    )
    return bot


def _sensors(*, x: float, y: float, vx: float, vy_up: float) -> Sensors:
    return Sensors(
        x=x,
        y=y,
        altitude=max(0.0, y),
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


def test_boost_clearance_probe_reports_negative_margin_for_targetward_progress() -> None:
    bot = _bot()
    probe = evaluate_boost_clearance_probe(
        bot,
        passive=_sensors(x=40.0, y=10.0, vx=22.0, vy_up=6.0),
        dx=760.0,
        action=BotAction(target_thrust=0.95, target_angle=0.45, refuel=False),
        max_power=24000.0,
        currently_active=False,
    )

    assert probe.active is True
    assert probe.min_margin is not None
    assert probe.min_margin < 0.0
    assert probe.worst_x is not None
    assert 85.0 <= probe.worst_x <= 230.0
    assert probe.angle_cap is not None
    assert 0.0 <= probe.angle_cap <= bot._cfg.progress_clearance_targetward_cap


def test_boost_clearance_guard_clamps_targetward_angle_and_raises_thrust() -> None:
    bot = _bot()
    bot._prev_angle_cmd = 0.45
    action, probe = apply_boost_clearance_guard(
        bot,
        passive=_sensors(x=40.0, y=10.0, vx=22.0, vy_up=6.0),
        dx=760.0,
        action=BotAction(target_thrust=0.50, target_angle=0.45, refuel=False),
        dt=0.05,
        prev_angle_cmd=0.0,
        max_power=24000.0,
        max_throttle=1.60,
        currently_active=False,
    )

    assert probe.active is True
    assert action.target_angle <= bot._cfg.progress_clearance_targetward_cap
    assert action.target_thrust == 1.52
    assert bot._prev_angle_cmd == action.target_angle


def test_boost_clearance_probe_stays_idle_after_rise_rejoin() -> None:
    bot = _bot()
    probe = evaluate_boost_clearance_probe(
        bot,
        passive=_sensors(x=260.0, y=90.0, vx=18.0, vy_up=12.0),
        dx=540.0,
        action=BotAction(target_thrust=0.90, target_angle=0.20, refuel=False),
        max_power=24000.0,
        currently_active=False,
    )

    assert probe.active is False


class _FlatSupportTerrain:
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


def test_boost_clearance_probe_uses_release_margin_when_already_active() -> None:
    bot = cast(Any, create_bot("pdg"))
    bot._cfg = replace(
        bot._cfg,
        progress_clearance_trigger_margin=2.0,
        progress_clearance_release_margin=8.0,
    )
    bot.vehicle_info = SimpleNamespace(height=20.0)
    bot.environment = BotEnvironment(
        terrain=_FlatSupportTerrain(),
        gravity_mag=9.8,
        target=BotTarget(uid="target", x=800.0, y=0.0, size=110.0),
        level_name="terrain",
        scenario_name="terrain:reactive:boost_clearance",
        scenario_params={
            "hazard_driver": "progress_clearance",
            "obstacle_support_x0": 85.0,
            "obstacle_support_x1": 230.0,
        },
    )
    passive = _sensors(x=40.0, y=17.0, vx=0.0, vy_up=0.0)
    action = BotAction(target_thrust=0.95, target_angle=0.0, refuel=False)

    inactive_probe = evaluate_boost_clearance_probe(
        bot,
        passive=passive,
        dx=760.0,
        action=action,
        max_power=24000.0,
        currently_active=False,
    )
    active_probe = evaluate_boost_clearance_probe(
        bot,
        passive=passive,
        dx=760.0,
        action=action,
        max_power=24000.0,
        currently_active=True,
    )

    assert inactive_probe.min_margin == active_probe.min_margin
    assert inactive_probe.active is False
    assert active_probe.active is True
