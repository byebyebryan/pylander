from __future__ import annotations

import argparse
import math
from dataclasses import replace
from types import SimpleNamespace

import main as main_module
import pytest
import bots.coast as coast_module
import bots.launch as launch_module
from bots._coast_tracking import (
    COAST_POLICY,
    CoastCourseConfig,
    apply_coast_guidance,
    coupled_brake_window,
    lateral_tracking_command,
    resolve_coast_behavior,
)
from bots._guidance_limits import cap_low_altitude_angle
from bots._guidance_types import GuidanceTargets
from bots._ballistics import ballistic_time_to_impact
from bots._launch_core import LaunchSetupConfig
from bots._targeting import pick_target
from bots import create_bot, list_available_bots
from bots.coast import should_handoff_to_flare
from bots.flare import FlareBot
from bots.plunge import PlungeBot
from bots.launch import (
    LaunchBot,
    apply_launch_setup_guidance,
    resolve_launch_behavior,
    should_handoff_to_coast,
)
from core.config import GRAVITY
from core.eval import aggregate_eval_records, normalize_run_result
from core.bot import Bot, BotAction, PassiveSensors, _ActiveSensorImpl
from core.components import (
    ActorControlRole,
    CargoHold,
    Engine,
    FuelTank,
    LandingSite,
    LandingSiteEconomy,
    LanderGeometry,
    LanderState,
    PhysicsState,
    PlayerControlled,
    PlayerSelectable,
    Radar,
    Transform,
)
from core.landing_sites import LandingSiteSurfaceModel
from core.maths import Vector2
from core.lander import Lander
from core.level import Level, LevelWorld
from core.sensor import RadarContact
from game import LanderGame, LoopTimers, _build_headless_stats
from main import RunConfig, _parse_args, _parse_seed_spec, _resolve_batch_plan, _run_batch
from levels import create_level as create_level_by_name
from levels.flat import create_level as create_level_flat
from levels.mountains import create_level as create_level_mountains
from levels.scenario_common import validate_scenario_recoverability
from ui.hud import HudOverlay


DRIFT_POLICY = COAST_POLICY
DriftCourseConfig = CoastCourseConfig
TransferSetupConfig = LaunchSetupConfig
apply_drift_guidance = apply_coast_guidance
apply_transfer_setup_guidance = apply_launch_setup_guidance
should_handoff_to_drift = should_handoff_to_coast


def resolve_drift_behavior(behavior: str):
    mapped = "coast" if behavior == "drift" else behavior
    key, policy, cfg = resolve_coast_behavior(mapped)
    if behavior == "drift":
        return "drift", policy, cfg
    return key, policy, cfg


def resolve_transfer_behavior(behavior: str):
    mapped = "launch" if behavior == "transfer" else behavior
    key, policy, cfg, setup_cfg = resolve_launch_behavior(mapped)
    if behavior == "transfer":
        return "transfer", policy, cfg, setup_cfg
    return key, policy, cfg, setup_cfg


def test_bot_registry_exposes_expected_bots() -> None:
    bots = list_available_bots()
    assert "plunge" in bots
    assert "flare" in bots
    assert "coast" in bots
    assert "launch" in bots
    assert "zem_zev" in bots
    assert "_drop_core" not in bots
    assert "_drift_core" not in bots
    assert "_transfer_core" not in bots
    assert "plunge_speed" not in bots
    assert "plunge_econ" not in bots
    assert "turtle" not in bots
    assert {"drop", "drift", "transfer", "ferry"}.isdisjoint(set(bots))
    plunge_bot = create_bot("plunge")
    flare_bot = create_bot("flare")
    coast_bot = create_bot("coast")
    launch_bot = create_bot("launch")
    zem_zev_bot = create_bot("zem_zev")
    assert plunge_bot.__class__.__name__ == "PlungeBot"
    assert flare_bot.__class__.__name__ == "FlareBot"
    assert coast_bot.__class__.__name__ == "CoastBot"
    assert launch_bot.__class__.__name__ == "LaunchBot"
    assert zem_zev_bot.__class__.__name__ == "ZemZevBot"


def test_zem_zev_bot_outputs_finite_action_for_flare_like_state() -> None:
    bot = create_bot("zem_zev")
    target = RadarContact(
        uid="eval_site_primary",
        x=0.0,
        y=0.0,
        size=110.0,
        angle=0.0,
        distance=600.0,
        rel_x=-420.0,
        rel_y=-430.0,
        is_inner_lock=True,
        info=None,
    )
    passive = PassiveSensors(
        x=420.0,
        y=430.0,
        altitude=430.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=-20.0,
        vy_up=9.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.3,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[target],
        proximity=None,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": -40.0,
                "hit_time": 6.0,
                "duration": 6.0,
            }

    action = bot.update(1.0 / 60.0, passive, active=_FakeActive())
    assert math.isfinite(action.target_thrust)
    assert math.isfinite(action.target_angle)
    assert 0.0 <= action.target_thrust <= 1.6
    assert abs(action.target_angle) <= 0.8


def test_zem_zev_bot_outputs_finite_action_for_plunge_like_state() -> None:
    bot = create_bot("zem_zev")
    passive = PassiveSensors(
        x=0.0,
        y=180.0,
        altitude=180.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.5,
        vy_up=-8.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.2,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": 0.0,
                "hit_time": 4.0,
                "duration": 4.0,
            }

    action = bot.update(1.0 / 60.0, passive, active=_FakeActive())
    assert math.isfinite(action.target_thrust)
    assert math.isfinite(action.target_angle)
    assert 0.0 <= action.target_thrust <= 1.6
    assert abs(action.target_angle) <= 0.8


def test_active_sensors_ballistic_trajectory_reports_hit_payload() -> None:
    sensors = _ActiveSensorImpl(
        origin_fn=lambda: Vector2(0.0, 0.0),
        radar_range_fn=lambda: 600.0,
        engine_adapter=None,
        terrain_fn=lambda _x: 0.0,
    )
    traj = sensors.ballistic_trajectory(
        x=0.0,
        y=140.0,
        vx=12.0,
        vy_up=0.0,
        max_distance=1800.0,
        segment_length=20.0,
        max_points=180,
    )
    assert traj["hit"]
    assert traj["termination"] == "terrain_hit"
    assert traj["hit_x"] is not None
    assert traj["hit_y"] is not None
    assert traj["hit_vx"] == pytest.approx(12.0)
    assert traj["hit_vy_up"] is not None
    assert traj["hit_speed"] is not None
    assert abs(float(traj["hit_y"])) <= 0.5
    assert len(traj["points"]) >= 2


def test_active_sensors_ballistic_trajectory_caches_repeat_queries(monkeypatch) -> None:
    call_count = 0

    def _fake_sample(*args, **kwargs):
        nonlocal call_count
        _ = args, kwargs
        call_count += 1
        return SimpleNamespace(
            points=[(0.0, 100.0), (10.0, 0.0)],
            hit=True,
            hit_x=10.0,
            hit_y=0.0,
            hit_time=1.0,
            hit_vx=10.0,
            hit_vy_up=-9.8,
            hit_speed=14.0,
            distance=100.0,
            duration=1.0,
            termination="terrain_hit",
        )

    monkeypatch.setattr("core.bot.sample_ballistic_trajectory", _fake_sample)
    sensors = _ActiveSensorImpl(
        origin_fn=lambda: Vector2(0.0, 0.0),
        radar_range_fn=lambda: 600.0,
        engine_adapter=None,
        terrain_fn=lambda _x: 0.0,
    )
    first = sensors.ballistic_trajectory(
        x=2.0,
        y=120.0,
        vx=10.0,
        vy_up=1.0,
    )
    second = sensors.ballistic_trajectory(
        x=2.0,
        y=120.0,
        vx=10.0,
        vy_up=1.0,
    )
    assert call_count == 1
    assert first == second


def test_ballistic_time_to_impact_prefers_sensor_hit_time() -> None:
    passive = PassiveSensors(
        x=0.0,
        y=150.0,
        altitude=150.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=8.0,
        vy_up=-1.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.2,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {"hit": True, "hit_time": 3.0, "duration": 3.0}

    t_sensor, src_sensor = ballistic_time_to_impact(passive, _FakeActive())
    t_fallback, src_fallback = ballistic_time_to_impact(passive, None)
    assert src_sensor == "sensor"
    assert t_sensor == pytest.approx(3.0)
    assert src_fallback == "analytic"
    assert t_fallback > t_sensor


def test_plunge_bot_engine_profile_fallback_uses_realistic_defaults() -> None:
    bot = PlungeBot()
    max_power, min_throttle, max_throttle, ramp_up = bot._engine_profile()
    assert max_power == pytest.approx(230000.0)
    assert min_throttle == pytest.approx(0.25)
    assert max_throttle == pytest.approx(1.6)
    assert ramp_up == pytest.approx(1.1)


def test_pick_target_prefers_first_radar_contact() -> None:
    passive = PassiveSensors(
        x=0.0,
        y=150.0,
        altitude=150.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-2.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.0,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[
            RadarContact(
                uid="first",
                x=5.0,
                y=0.0,
                size=110.0,
                angle=0.0,
                distance=500.0,
                rel_x=5.0,
                rel_y=-150.0,
                is_inner_lock=False,
                info=None,
            ),
            RadarContact(
                uid="second",
                x=0.0,
                y=0.0,
                size=110.0,
                angle=0.0,
                distance=10.0,
                rel_x=0.0,
                rel_y=-150.0,
                is_inner_lock=True,
                info=None,
            ),
        ],
        proximity=None,
    )
    target = pick_target(passive)
    assert target is not None
    assert target.uid == "first"


def test_plunge_behavior_rejects_non_balanced_modes() -> None:
    with pytest.raises(ValueError, match="Expected one of: balanced"):
        PlungeBot(behavior="econ")
    with pytest.raises(ValueError, match="Expected one of: balanced"):
        PlungeBot(behavior="speed")


def test_plunge_balanced_behavior_blocks_overdrive_when_fuel_margin_is_low() -> None:
    bot = PlungeBot()
    passive = PassiveSensors(
        x=0.0,
        y=100.0,
        altitude=20.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-8.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=1.0,
        fuel=8.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    assert not bot._can_use_overdrive(passive, vertical_mode="terminal_burn", alt=8.0)


def test_plunge_status_prefix_uses_balanced_mode() -> None:
    bot = PlungeBot()
    passive = PassiveSensors(
        x=0.0,
        y=0.0,
        altitude=0.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.12,
        ax=0.0,
        ay_up=0.0,
        mass=1.0,
        thrust_level=0.0,
        fuel=0.0,
        max_fuel=100.0,
        state="landed",
        radar_contacts=[],
        proximity=None,
    )
    action = bot.update(1.0 / 60.0, passive, active=None)
    assert action.status.startswith("plunge:")


def test_plunge_bot_headless_stats_include_ballistic_summary() -> None:
    bot = PlungeBot()
    passive = PassiveSensors(
        x=0.0,
        y=140.0,
        altitude=140.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=2.0,
        vy_up=-1.5,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.1,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {"hit": True, "hit_time": 4.0, "duration": 4.0}

    _ = bot.update(1.0 / 60.0, passive, active=_FakeActive())
    stats = bot.get_headless_stats()
    assert "ball tti:" in stats


def test_plunge_guidance_handles_analytic_and_sensor_impact_sources(monkeypatch) -> None:
    bot = PlungeBot()
    passive = PassiveSensors(
        x=0.0,
        y=180.0,
        altitude=180.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-4.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.0,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    target = RadarContact(
        uid="eval_site_primary",
        x=0.0,
        y=0.0,
        size=110.0,
        angle=0.0,
        distance=180.0,
        rel_x=0.0,
        rel_y=-180.0,
        is_inner_lock=True,
        info=None,
    )
    max_power, _, max_throttle, ramp_up = bot._engine_profile()
    max_force = max_power * max_throttle

    monkeypatch.setattr(
        "bots.plunge.ballistic_time_to_impact",
        lambda _passive, _active: (1.2, "analytic"),
    )
    analytic_guidance = bot._guidance(
        passive,
        target,
        max_force=max_force,
        max_throttle=max_throttle,
        ramp_up=ramp_up,
    )

    monkeypatch.setattr(
        "bots.plunge.ballistic_time_to_impact",
        lambda _passive, _active: (1.2, "sensor"),
    )
    sensor_guidance = bot._guidance(
        passive,
        target,
        max_force=max_force,
        max_throttle=max_throttle,
        ramp_up=ramp_up,
    )

    assert analytic_guidance.vertical_mode in {"coast", "terminal_burn", "flare"}
    assert sensor_guidance.vertical_mode in {"coast", "terminal_burn", "flare"}
    assert math.isfinite(float(analytic_guidance.burn_altitude))
    assert math.isfinite(float(sensor_guidance.burn_altitude))


def test_plunge_balanced_overdrive_requires_terminal_mode() -> None:
    bot = PlungeBot()
    passive = PassiveSensors(
        x=0.0,
        y=100.0,
        altitude=30.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-7.5,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=1.0,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    assert not bot._can_use_overdrive(passive, vertical_mode="flare", alt=30.0)


def test_apply_drift_guidance_pushes_large_offset_into_correction_mode() -> None:
    cfg = DriftCourseConfig()
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.4,
        vy_sp=-1.2,
        dx=90.0,
        alt=60.0,
        burn_altitude=20.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=0.0)
    assert adjusted.phase == "coast"
    assert adjusted.vertical_mode == "coast"
    assert abs(adjusted.vx_sp) >= cfg.correction_vx_min


def test_apply_drift_guidance_accelerates_coast_descent_at_high_altitude() -> None:
    cfg = DriftCourseConfig()
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-1.0,
        dx=0.0,
        alt=120.0,
        burn_altitude=30.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg)
    assert adjusted.phase == "coast"
    assert adjusted.vertical_mode == "coast"
    assert adjusted.vy_sp < guidance.vy_sp


def test_apply_drift_guidance_uses_projected_ballistic_error() -> None:
    cfg = DriftCourseConfig()
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.4,
        vy_sp=-1.2,
        dx=40.0,
        alt=60.0,
        burn_altitude=20.0,
    )
    t_fall = max(0.5, math.sqrt((2.0 * 9.8 * guidance.alt)) / 9.8)
    on_target_vx = guidance.dx / t_fall
    adjusted_on_target = apply_drift_guidance(guidance, cfg, vx=on_target_vx, vy_up=0.0)
    assert adjusted_on_target.vertical_mode == "coast"
    assert adjusted_on_target.vx_sp == pytest.approx(on_target_vx)

    adjusted_off_target = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=0.0)
    assert adjusted_off_target.vertical_mode == "coast"
    assert abs(adjusted_off_target.vx_sp) >= cfg.correction_vx_min


def test_apply_drift_guidance_prefers_sensor_projection_when_available() -> None:
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.4,
        vy_sp=-1.2,
        dx=20.0,
        alt=100.0,
        burn_altitude=20.0,
    )
    cfg = DriftCourseConfig()
    baseline = apply_drift_guidance(guidance, cfg, vx=5.0, vy_up=0.0)

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": -140.0,
                "hit_time": 5.0,
                "duration": 5.0,
            }

    sensor_guidance = apply_drift_guidance(
        guidance,
        cfg,
        vx=5.0,
        vy_up=0.0,
        active=_FakeActive(),
        x=0.0,
        y=160.0,
    )
    assert abs(sensor_guidance.vx_sp) > abs(baseline.vx_sp)


def test_drift_bot_headless_stats_include_ballistic_projection_summary() -> None:
    bot = create_bot("coast")
    target = RadarContact(
        uid="eval_site_primary",
        x=0.0,
        y=0.0,
        size=110.0,
        angle=0.0,
        distance=180.0,
        rel_x=-40.0,
        rel_y=-120.0,
        is_inner_lock=True,
        info=None,
    )
    passive = PassiveSensors(
        x=40.0,
        y=120.0,
        altitude=120.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=-4.0,
        vy_up=-1.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.3,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[target],
        proximity=None,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": -50.0,
                "hit_time": 5.0,
                "duration": 5.0,
            }

    _ = bot.update(1.0 / 60.0, passive, active=_FakeActive())
    stats = bot.get_headless_stats()
    assert "ball pdx:" in stats


def test_apply_drift_guidance_forces_thrust_backed_correction_for_high_vx_on_track() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.8,
        vy_sp=-1.4,
        dx=220.0,
        alt=160.0,
        burn_altitude=20.0,
    )
    t_fall = max(0.5, math.sqrt((2.0 * 9.8 * guidance.alt)) / 9.8)
    on_track_high_vx = guidance.dx / t_fall
    adjusted = apply_drift_guidance(
        guidance,
        cfg,
        vx=on_track_high_vx,
        vy_up=0.0,
    )
    assert adjusted.vertical_mode == "coast"


def test_apply_drift_guidance_enters_drift_coast_when_fast_and_far_off_track() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.6,
        vy_sp=-1.3,
        dx=140.0,
        alt=80.0,
        burn_altitude=20.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg, vx=12.0, vy_up=-1.2)
    assert adjusted.vertical_mode == "coast_hold"


def test_coupled_brake_window_prefers_earlier_lateral_brake() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    window = coupled_brake_window(
        cfg,
        alt=180.0,
        dx=90.0,
        vx=32.0,
        vy_up=-12.0,
        mass=12000.0,
        max_force=230000.0 * 1.6,
        max_tilt=0.56,
        spool_time=0.35,
        vertical_brake_alt=40.0,
    )
    assert window.lateral_brake_alt > window.vertical_brake_alt
    assert window.combined_brake_alt == pytest.approx(window.lateral_brake_alt)


def test_coupled_brake_window_preserves_vertical_when_lateral_not_urgent() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    window = coupled_brake_window(
        cfg,
        alt=160.0,
        dx=220.0,
        vx=3.0,
        vy_up=-14.0,
        mass=12000.0,
        max_force=230000.0 * 1.6,
        max_tilt=0.56,
        spool_time=0.35,
        vertical_brake_alt=52.0,
    )
    assert window.lateral_brake_alt == pytest.approx(0.0)
    assert window.combined_brake_alt == pytest.approx(window.vertical_brake_alt)


def test_resolve_drift_behavior_exposes_single_unified_profile() -> None:
    key, _, _ = resolve_drift_behavior("drift")
    assert key == "drift"
    with pytest.raises(ValueError):
        resolve_drift_behavior("accuracy")


def test_resolve_transfer_behavior_exposes_single_profile() -> None:
    key, _, _, _ = resolve_transfer_behavior("transfer")
    assert key == "transfer"
    with pytest.raises(ValueError):
        resolve_transfer_behavior("ferry")
    with pytest.raises(ValueError):
        resolve_transfer_behavior("accuracy")


def test_projection_lateral_error_is_disabled_for_drift_only() -> None:
    assert DRIFT_POLICY.use_projected_lateral_error is False
    _, transfer_policy, _, _ = resolve_transfer_behavior("transfer")
    assert transfer_policy.use_projected_lateral_error is True


def test_apply_transfer_setup_guidance_uses_dedicated_sideburn_phase() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig(
        setup_descent_vy_target=-2.0,
    )
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.4,
        dx=240.0,
        alt=190.0,
        burn_altitude=28.0,
    )
    adjusted = apply_transfer_setup_guidance(
        guidance,
        cfg,
        setup_cfg,
        vx=0.0,
        vy_up=-1.0,
    )
    assert adjusted.phase == "launch_setup_sideburn"
    assert adjusted.vertical_mode == "launch_sideburn"
    assert adjusted.vy_sp == pytest.approx(-2.0)


def test_apply_transfer_setup_guidance_uses_thrust_backed_side_burn_for_non_climb_setup() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig(
        setup_descent_vy_target=-1.6,
    )
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-5.8,
        dx=160.0,
        alt=220.0,
        burn_altitude=28.0,
    )
    adjusted = apply_transfer_setup_guidance(
        guidance,
        cfg,
        setup_cfg,
        vx=0.0,
        vy_up=0.0,
    )
    assert adjusted.phase == "launch_setup_sideburn"
    assert adjusted.vertical_mode == "launch_sideburn"
    assert adjusted.vy_sp == pytest.approx(-1.6)
    assert abs(adjusted.vx_sp) >= setup_cfg.setup_vx_floor


def test_apply_transfer_setup_guidance_uses_sensor_projection_when_available() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig(
        setup_response_delay_s=0.0,
        setup_vx_floor=1.0,
    )
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.0,
        dx=140.0,
        alt=240.0,
        burn_altitude=32.0,
    )

    class _FakeActive:
        def __init__(self) -> None:
            self.calls = 0

        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            self.calls += 1
            return {
                "hit": True,
                "hit_x": 80.0,
                "hit_time": 4.0,
                "duration": 4.0,
            }

    active = _FakeActive()
    adjusted = apply_transfer_setup_guidance(
        guidance,
        cfg,
        setup_cfg,
        vx=4.0,
        vy_up=-1.0,
        active=active,
        x=20.0,
        y=260.0,
    )
    assert active.calls == 1
    assert adjusted.vx_sp == pytest.approx(24.0)


def test_apply_transfer_setup_guidance_falls_back_when_sensor_has_no_hit() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig(setup_response_delay_s=0.0)
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.0,
        dx=140.0,
        alt=240.0,
        burn_altitude=32.0,
    )

    class _FakeActiveNoHit:
        def __init__(self) -> None:
            self.calls = 0

        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            self.calls += 1
            return {
                "hit": False,
                "hit_x": None,
                "hit_time": None,
                "duration": 3.0,
                "termination": "point_budget",
            }

    active = _FakeActiveNoHit()
    baseline = apply_transfer_setup_guidance(
        guidance,
        cfg,
        setup_cfg,
        vx=4.0,
        vy_up=-1.0,
        x=20.0,
        y=260.0,
    )
    adjusted = apply_transfer_setup_guidance(
        guidance,
        cfg,
        setup_cfg,
        vx=4.0,
        vy_up=-1.0,
        active=active,
        x=20.0,
        y=260.0,
    )
    assert active.calls == 1
    assert adjusted.vx_sp == pytest.approx(baseline.vx_sp)


def test_should_handoff_to_drift_requires_low_projected_error() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig()
    near_track = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-1.8,
        dx=8.0,
        alt=120.0,
        burn_altitude=26.0,
    )
    far_track = replace(near_track, dx=220.0)
    assert should_handoff_to_drift(
        near_track,
        cfg,
        setup_cfg,
        vx=1.2,
        vy_up=-0.8,
    )
    assert not should_handoff_to_drift(
        far_track,
        cfg,
        setup_cfg,
        vx=1.2,
        vy_up=-0.8,
    )


def test_should_handoff_to_drift_uses_sensor_projection_when_available() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig(setup_response_delay_s=0.0)
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.2,
        dx=120.0,
        alt=560.0,
        burn_altitude=30.0,
    )

    class _FakeActive:
        def __init__(self, hit_x: float) -> None:
            self.hit_x = hit_x

        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": self.hit_x,
                "hit_time": 6.0,
                "duration": 6.0,
            }

    x_now = 40.0
    y_now = 640.0
    target_x = x_now + guidance.dx
    on_track = should_handoff_to_drift(
        guidance,
        cfg,
        setup_cfg,
        vx=0.0,
        vy_up=-1.0,
        active=_FakeActive(hit_x=target_x),
        x=x_now,
        y=y_now,
    )
    far_track = should_handoff_to_drift(
        guidance,
        cfg,
        setup_cfg,
        vx=0.0,
        vy_up=-1.0,
        active=_FakeActive(hit_x=target_x - 260.0),
        x=x_now,
        y=y_now,
    )
    assert on_track
    assert not far_track


def test_should_handoff_to_drift_rejects_predicted_track_without_current_alignment() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    setup_cfg = TransferSetupConfig()
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.0,
        dx=-200.0,
        alt=560.0,
        burn_altitude=30.0,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args
            x = float(kwargs.get("x", 0.0))
            if x < -10.0:
                hit_x = -200.0
            else:
                hit_x = -120.0
            return {
                "hit": True,
                "hit_x": hit_x,
                "hit_time": 6.0,
                "duration": 6.0,
            }

    debug: dict[str, object] = {}
    handoff = should_handoff_to_drift(
        guidance,
        cfg,
        setup_cfg,
        vx=-50.0,
        vy_up=-1.0,
        active=_FakeActive(),
        x=0.0,
        y=640.0,
        debug=debug,
    )
    assert not handoff
    assert bool(debug.get("on_track"))
    assert not bool(debug.get("current_guard_pass"))


def test_transfer_bot_guidance_handoff_uses_drift_guidance_function(monkeypatch) -> None:
    bot = LaunchBot()
    bot._setup_cfg = replace(  # force quick handoff in this narrow unit test
        bot._setup_cfg,
        handoff_projected_dx_ratio=2.0,
    )
    target = RadarContact(
        uid="eval_site_primary",
        x=0.0,
        y=0.0,
        size=110.0,
        angle=0.0,
        distance=126.5,
        rel_x=-40.0,
        rel_y=-120.0,
        is_inner_lock=True,
        info=None,
    )
    passive = PassiveSensors(
        x=40.0,
        y=120.0,
        altitude=120.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=-8.0,
        vy_up=-1.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.5,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[target],
        proximity=None,
    )

    calls: list[tuple[float | None, float | None]] = []

    def _fake_apply(
        guidance: GuidanceTargets,
        _cfg: DriftCourseConfig,
        *,
        vx,
        vy_up,
        active=None,
        x=None,
        y=None,
        clearance=0.0,
        debug=None,
    ):
        _ = active, x, y, clearance, debug
        calls.append((vx, vy_up))
        return replace(guidance, phase="coast_handoff")

    monkeypatch.setattr(launch_module, "apply_coast_guidance", _fake_apply)

    first_guidance = bot._guidance(
        passive,
        target,
        max_force=230000.0 * 1.6,
        max_throttle=1.6,
        ramp_up=1.1,
    )
    assert first_guidance.phase == "launch_setup_sideburn"
    assert calls == []

    second_guidance = bot._guidance(
        passive,
        target,
        max_force=230000.0 * 1.6,
        max_throttle=1.6,
        ramp_up=1.1,
    )
    assert calls == [(-8.0, -1.0)]
    assert second_guidance.phase == "coast_handoff"


def test_transfer_sideburn_allocation_targets_near_full_rotation() -> None:
    bot = LaunchBot()
    bot._last_guidance = GuidanceTargets(
        phase="launch_setup_sideburn",
        vertical_mode="launch_sideburn",
        vx_sp=8.0,
        vy_sp=-2.2,
        dx=200.0,
        alt=300.0,
        burn_altitude=60.0,
    )
    passive = PassiveSensors(
        x=0.0,
        y=300.0,
        altitude=300.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-2.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.5,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    action = bot._allocate_controls(
        dt=1.0,
        passive=passive,
        a_x_sp=6.0,
        a_up_sp=0.0,
        alt=300.0,
        dx=200.0,
        vertical_mode="launch_sideburn",
    )
    assert abs(action.target_angle) >= 1.2
    assert action.target_thrust >= bot._setup_cfg.setup_sideburn_min_thrust


def test_transfer_sideburn_allocation_keeps_thrust_while_sensor_miss_is_outside_cone() -> None:
    bot = LaunchBot()
    bot._last_guidance = GuidanceTargets(
        phase="launch_setup_sideburn",
        vertical_mode="launch_sideburn",
        vx_sp=0.0,
        vy_sp=-2.2,
        dx=220.0,
        alt=320.0,
        burn_altitude=64.0,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": -260.0,
                "hit_time": 7.0,
                "duration": 7.0,
            }

    bot._active_sensors = _FakeActive()
    passive = PassiveSensors(
        x=0.0,
        y=320.0,
        altitude=320.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-2.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.5,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    action = bot._allocate_controls(
        dt=1.0,
        passive=passive,
        a_x_sp=0.0,
        a_up_sp=0.0,
        alt=320.0,
        dx=220.0,
        vertical_mode="launch_sideburn",
    )
    bot._active_sensors = None
    assert action.target_thrust >= bot._setup_cfg.setup_sideburn_min_thrust


def test_transfer_sideburn_allocation_keeps_thrust_when_inside_cone_outside_target() -> None:
    bot = LaunchBot()
    bot._last_target_size = 110.0
    bot._last_guidance = GuidanceTargets(
        phase="launch_setup_sideburn",
        vertical_mode="launch_sideburn",
        vx_sp=0.0,
        vy_sp=-2.2,
        dx=80.0,
        alt=250.0,
        burn_altitude=56.0,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": 10.0,
                "hit_time": 4.0,
                "duration": 4.0,
            }

    bot._active_sensors = _FakeActive()
    passive = PassiveSensors(
        x=0.0,
        y=250.0,
        altitude=250.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-2.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=12000.0,
        thrust_level=0.5,
        fuel=80.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    action = bot._allocate_controls(
        dt=1.0,
        passive=passive,
        a_x_sp=0.0,
        a_up_sp=0.0,
        alt=250.0,
        dx=80.0,
        vertical_mode="launch_sideburn",
    )
    bot._active_sensors = None
    assert action.target_thrust >= bot._setup_cfg.setup_sideburn_min_thrust


def test_coast_handoff_to_flare_requires_consecutive_pass_frames() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.0,
        dx=-10.0,
        alt=120.0,
        burn_altitude=30.0,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": 0.0,
                "hit_time": 4.0,
                "duration": 4.0,
            }

    retrograde_angle = math.atan2(3.0, 1.0)
    debug: dict[str, object] = {}
    first_ready = should_handoff_to_flare(
        guidance,
        cfg,
        vx=-3.0,
        vy_up=-1.0,
        angle_rad=retrograde_angle,
        active=_FakeActive(),
        x=10.0,
        y=120.0,
        target_size=110.0,
        consecutive_passes=0,
        required_passes=3,
        debug=debug,
    )
    assert not first_ready
    assert bool(debug.get("raw_ready"))
    assert int(debug.get("pass_count_after_sample", -1)) == 1
    assert int(debug.get("required_passes", -1)) == 3

    second_ready = should_handoff_to_flare(
        guidance,
        cfg,
        vx=-3.0,
        vy_up=-1.0,
        angle_rad=retrograde_angle,
        active=_FakeActive(),
        x=10.0,
        y=120.0,
        target_size=110.0,
        consecutive_passes=2,
        required_passes=3,
    )
    assert second_ready


def test_coast_handoff_cfg_uses_course_handoff_fields() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    tuned_cfg = replace(
        cfg,
        flare_handoff_altitude_max=123.0,
        flare_handoff_center_tolerance=4.5,
        flare_handoff_vx_err_cap=2.75,
        flare_handoff_require_burn_imminent=False,
        flare_handoff_burn_altitude_margin=77.0,
        flare_handoff_burn_time_margin=0.8,
        flare_handoff_t_fall_max=6.25,
        flare_handoff_consecutive_pass_frames=5,
    )
    handoff_cfg = coast_module._resolve_handoff_cfg(tuned_cfg)
    assert handoff_cfg.altitude_max == pytest.approx(123.0)
    assert handoff_cfg.center_tolerance == pytest.approx(4.5)
    assert handoff_cfg.vx_err_cap == pytest.approx(2.75)
    assert handoff_cfg.require_burn_imminent is False
    assert handoff_cfg.burn_altitude_margin == pytest.approx(77.0)
    assert handoff_cfg.burn_time_margin == pytest.approx(0.8)
    assert handoff_cfg.t_fall_max == pytest.approx(6.25)
    assert handoff_cfg.consecutive_pass_frames == 5


def test_coast_handoff_to_flare_requires_retrograde_alignment() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.0,
        vy_sp=-2.0,
        dx=-10.0,
        alt=120.0,
        burn_altitude=30.0,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": 0.0,
                "hit_time": 4.0,
                "duration": 4.0,
            }

    retrograde_angle = math.atan2(3.0, 1.0)
    aligned = should_handoff_to_flare(
        guidance,
        cfg,
        vx=-3.0,
        vy_up=-1.0,
        angle_rad=retrograde_angle,
        active=_FakeActive(),
        x=10.0,
        y=120.0,
        target_size=110.0,
        consecutive_passes=2,
        required_passes=3,
    )
    assert aligned

    debug: dict[str, object] = {}
    misaligned = should_handoff_to_flare(
        guidance,
        cfg,
        vx=-3.0,
        vy_up=-1.0,
        angle_rad=retrograde_angle + math.radians(70.0),
        active=_FakeActive(),
        x=10.0,
        y=120.0,
        target_size=110.0,
        consecutive_passes=2,
        required_passes=3,
        debug=debug,
    )
    assert not misaligned
    assert bool(debug.get("retrograde_ready")) is False


def test_flare_sideburn_direction_lock_avoids_early_flip() -> None:
    bot = FlareBot()
    first = bot._resolve_sideburn_direction(projected_dx=60.0, dx=60.0, vx=-10.0)
    second = bot._resolve_sideburn_direction(projected_dx=-55.0, dx=-55.0, vx=-10.0)
    assert first == pytest.approx(1.0)
    assert second == pytest.approx(1.0)
    third = bot._resolve_sideburn_direction(projected_dx=-3.0, dx=-3.0, vx=-0.5)
    assert third == pytest.approx(-1.0)


def test_flare_bot_mini_matrix_success_guardrail() -> None:
    config = RunConfig(
        level_name="flare",
        bot_name="flare",
        bot_behavior=None,
        headless=True,
        batch=False,
        print_freq=0,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds=None,
        batch_levels=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
        scenario_name=None,
        batch_scenarios=None,
    )
    records = []
    for scenario in ("shallower", "mid", "steeper"):
        for seed in (0, 1):
            records.append(
                main_module._run_once_record(
                    config,
                    seed=seed,
                    level_name="flare",
                    eval_scenario_name=scenario,
                )
            )
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 6
    assert summary["successes"] == 6
    assert summary["success_rate"] == pytest.approx(1.0)


def test_lateral_tracking_command_increases_vx_target_for_large_offset() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    cmd = lateral_tracking_command(
        cfg,
        dx=120.0,
        alt=80.0,
        vx=0.0,
        vy_up=-1.0,
        ax=0.0,
        vx_guidance=0.4,
    )
    assert cmd.vx_target > 0.4
    assert cmd.ax_target > 0.0


def test_lateral_tracking_command_uses_sensor_projection_to_reduce_correction() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    baseline = lateral_tracking_command(
        cfg,
        dx=4.0,
        alt=80.0,
        vx=0.0,
        vy_up=-1.0,
        ax=0.0,
        vx_guidance=0.4,
    )

    class _FakeActive:
        def ballistic_trajectory(self, *args, **kwargs):
            _ = args, kwargs
            return {
                "hit": True,
                "hit_x": 4.0,
                "hit_time": 0.6,
                "duration": 0.6,
            }

    sensor = lateral_tracking_command(
        cfg,
        dx=4.0,
        alt=80.0,
        vx=0.0,
        vy_up=-1.0,
        ax=0.0,
        vx_guidance=0.4,
        active=_FakeActive(),
        x=0.0,
        y=80.0,
    )
    assert sensor.vx_target < baseline.vx_target
    assert sensor.ax_target > baseline.ax_target


def test_lateral_tracking_command_softens_near_touchdown_window() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    far = lateral_tracking_command(
        cfg,
        dx=10.0,
        alt=40.0,
        vx=0.0,
        vy_up=-0.5,
        ax=0.0,
        vx_guidance=1.0,
    )
    near = lateral_tracking_command(
        cfg,
        dx=10.0,
        alt=8.0,
        vx=0.0,
        vy_up=-0.5,
        ax=0.0,
        vx_guidance=1.0,
    )
    assert abs(near.ax_target) < abs(far.ax_target)


def test_lateral_tracking_command_limits_speed_by_remaining_stop_distance() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    cmd = lateral_tracking_command(
        cfg,
        dx=36.0,
        alt=180.0,
        vx=38.0,
        vy_up=-8.0,
        ax=0.0,
        vx_guidance=7.0,
    )
    vx_stop_cap = math.sqrt(2.0 * cfg.lateral_stop_accel_estimate * 36.0) * cfg.lateral_stop_vx_margin
    assert abs(cmd.vx_target) <= (vx_stop_cap + 1e-6)


def test_lateral_tracking_command_is_deterministic_for_fixed_inputs() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    first = lateral_tracking_command(
        cfg,
        dx=-84.0,
        alt=52.0,
        vx=2.5,
        vy_up=-1.8,
        ax=-0.6,
        vx_guidance=-1.2,
    )
    second = lateral_tracking_command(
        cfg,
        dx=-84.0,
        alt=52.0,
        vx=2.5,
        vy_up=-1.8,
        ax=-0.6,
        vx_guidance=-1.2,
    )
    assert second.vx_target == pytest.approx(first.vx_target)
    assert second.ax_target == pytest.approx(first.ax_target)


def test_apply_drift_guidance_terminal_enforces_minimum_tracking_speed() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="terminal_burn",
        vertical_mode="terminal_burn",
        vx_sp=0.2,
        vy_sp=-1.2,
        dx=120.0,
        alt=60.0,
        burn_altitude=20.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=-1.2)
    assert abs(adjusted.vx_sp) >= cfg.terminal_burn_correction_vx_floor


def test_apply_drift_guidance_terminal_zero_vx_clamp_only_near_ground() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="terminal_burn",
        vertical_mode="terminal_burn",
        vx_sp=4.0,
        vy_sp=-1.2,
        dx=10.0,
        alt=40.0,
        burn_altitude=20.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=-3.0)
    assert abs(adjusted.vx_sp) > cfg.lateral_terminal_zero_vx_cap


def test_apply_drift_guidance_terminal_keeps_enough_vx_to_reach_target() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="terminal_burn",
        vertical_mode="terminal_burn",
        vx_sp=0.6,
        vy_sp=-1.2,
        dx=110.0,
        alt=55.0,
        burn_altitude=20.0,
    )
    t_fall = max(0.5, math.sqrt((2.0 * 9.8 * guidance.alt)) / 9.8)
    under_speed_vx = (guidance.dx / t_fall) - 4.0
    adjusted = apply_drift_guidance(guidance, cfg, vx=under_speed_vx, vy_up=0.0)
    assert abs(adjusted.vx_sp) > abs(guidance.vx_sp)


def test_apply_drift_guidance_terminal_can_exceed_low_altitude_vx_cap_when_needed() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="terminal_burn",
        vertical_mode="terminal_burn",
        vx_sp=0.6,
        vy_sp=-1.2,
        dx=60.0,
        alt=18.0,
        burn_altitude=10.0,
    )
    adjusted = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=0.0)
    assert abs(adjusted.vx_sp) > cfg.correction_vx_low_alt_cap


def test_cap_low_altitude_angle_only_applies_inside_touchdown_window() -> None:
    cfg = DriftCourseConfig()
    assert cap_low_altitude_angle(0.4, alt=8.0, dx=10.0, cfg=cfg) == pytest.approx(0.16)
    assert cap_low_altitude_angle(-0.4, alt=8.0, dx=10.0, cfg=cfg) == pytest.approx(-0.16)
    assert cap_low_altitude_angle(0.4, alt=40.0, dx=10.0, cfg=cfg) == pytest.approx(0.4)
    assert cap_low_altitude_angle(0.4, alt=8.0, dx=40.0, cfg=cfg) == pytest.approx(0.4)


class _FlatTerrain:
    def __call__(self, _x: float, lod: int = 0) -> float:
        return 0.0

    def get_resolution(self, _lod: int) -> float:
        return 1.0


class _FixedTerrainLevel:
    def terrain(self, _x: float) -> float:
        return 20.0


class _PassiveBot(Bot):
    def update(self, dt, passive, active) -> BotAction:  # noqa: D401
        return BotAction(target_thrust=0.0, target_angle=passive.angle, refuel=False)


class _ShortLevel(Level):
    def __init__(self, stop_after_updates: int = 3):
        self.stop_after_updates = stop_after_updates
        self.update_calls = 0

    def setup(self, _game, seed: int) -> None:
        _ = seed
        self.world = LevelWorld(
            terrain=_FlatTerrain(),
            sites=LandingSiteSurfaceModel(),
            lander=Lander(start_pos=Vector2(0.0, 100.0)),
        )

    def update(self, game, dt: float) -> None:
        _ = game, dt
        self.update_calls += 1

    def should_end(self, game) -> bool:
        _ = game
        return self.update_calls >= self.stop_after_updates

    def end(self, game):
        ls = game.lander.get_component(LanderState)
        if ls is None:
            raise RuntimeError("Lander missing LanderState component")
        return {
            "updates": self.update_calls,
            "elapsed_time": getattr(game, "_elapsed_time", 0.0),
            "state": ls.state,
        }


class _TwoActorLevel(Level):
    def __init__(self):
        self.update_calls = 0

    def setup(self, _game, seed: int) -> None:
        _ = seed
        actor_a = Lander(start_pos=Vector2(0.0, 100.0))
        actor_a.uid = "actor_human"
        actor_a.add_component(ActorControlRole(role="human"))
        actor_a.add_component(PlayerSelectable(order=0))
        actor_a.add_component(PlayerControlled(active=True))

        actor_b = Lander(start_pos=Vector2(20.0, 100.0))
        actor_b.uid = "actor_bot"
        actor_b.add_component(ActorControlRole(role="bot"))
        actor_b.add_component(PlayerSelectable(order=1))

        self.world = LevelWorld(
            terrain=_FlatTerrain(),
            sites=LandingSiteSurfaceModel(),
            lander=actor_a,
            actors=[actor_a, actor_b],
            primary_actor_uid=actor_a.uid,
        )

    def update(self, game, dt: float) -> None:
        _ = game, dt
        self.update_calls += 1

    def should_end(self, game) -> bool:
        _ = game
        return self.update_calls >= 1

    def end(self, game):
        return {"active_uid": game.active_player_actor_uid}


class _FakeEngine:
    def __init__(self):
        self.pose = (Vector2(0.0, 100.0), 0.0)
        self.velocity = (Vector2(0.0, 0.0), 0.0)
        self.mass_updates: list[float] = []

    def set_lander_mass(self, mass: float, uid: str | None = None) -> None:
        _ = uid
        self.mass_updates.append(float(mass))

    def set_lander_controls(self, _thrust_force: float, _angle: float) -> None:
        pass

    def override(self, _angle: float) -> None:
        pass

    def apply_force(self, _force: Vector2, _point: Vector2 | None = None) -> None:
        pass

    def step(self, _dt: float) -> None:
        pass

    def get_pose(self) -> tuple[Vector2, float]:
        return self.pose

    def get_velocity(self) -> tuple[Vector2, float]:
        return self.velocity

    def get_contact_report(self) -> dict:
        return {"colliding": False, "normal": None, "rel_speed": 0.0, "point": None}

    def teleport_lander(
        self,
        pos: Vector2,
        angle: float | None = None,
        clear_velocity: bool = True,
    ) -> None:
        _ = clear_velocity
        self.pose = (Vector2(pos), 0.0 if angle is None else angle)

    def raycast(self, _origin: Vector2, _angle: float, _max_distance: float) -> dict:
        return {"hit": False, "hit_x": 0.0, "hit_y": 0.0, "distance": None}


def test_validate_scenario_recoverability_allows_reasonable_inputs() -> None:
    actor = Lander(start_pos=Vector2(0.0, 200.0))
    validate_scenario_recoverability(
        actor,
        scenario_name="ok_case",
        spawn_clearance=300.0,
        initial_vy_up=-4.0,
    )


def test_validate_scenario_recoverability_rejects_unthrustable_setup() -> None:
    actor = Lander(start_pos=Vector2(0.0, 200.0))
    engine = actor.get_component(Engine)
    assert engine is not None
    engine.max_power = 0.0
    with pytest.raises(ValueError, match="no upward acceleration"):
        validate_scenario_recoverability(
            actor,
            scenario_name="bad_case",
            spawn_clearance=300.0,
            initial_vy_up=-4.0,
        )


def test_headless_mode_requires_bot() -> None:
    level = _ShortLevel()
    try:
        LanderGame(level=level, headless=True)
    except ValueError as exc:
        assert "requires a bot" in str(exc)
    else:
        raise AssertionError("Expected ValueError when running headless without a bot")


def test_game_run_returns_level_result_and_advances_time() -> None:
    level = _ShortLevel(stop_after_updates=3)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)

    result = game.run(print_freq=0, max_steps=100)

    assert result["updates"] == 3
    assert result["state"] == "flying"
    assert result["elapsed_time"] > 0.0
    assert game._elapsed_time == result["elapsed_time"]


def test_headless_print_freq_respects_step_frequency() -> None:
    level = _ShortLevel(stop_after_updates=5)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)
    calls = {"count": 0}

    def _count_stats(_timers) -> None:
        calls["count"] += 1

    game._print_headless_stats = _count_stats
    game.run(print_freq=2, max_steps=100)

    assert calls["count"] == 2


def test_game_run_emits_efficiency_metrics() -> None:
    level = _ShortLevel(stop_after_updates=3)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)

    result = game.run(print_freq=0, max_steps=100)

    for key in (
        "distance_flown",
        "landing_offset",
        "avg_speed",
        "fuel_consumed",
        "fuel_remaining",
        "fuel_per_distance",
        "spawn_to_target_distance",
        "path_efficiency",
        "time_to_first_land",
    ):
        assert key in result
    assert result["distance_flown"] >= 0.0
    assert result["avg_speed"] >= 0.0
    assert result["fuel_consumed"] >= 0.0
    assert result["fuel_per_distance"] >= 0.0


def test_game_run_records_landing_distance_from_target_center_when_landed() -> None:
    level = _ShortLevel(stop_after_updates=1)
    level.eval_target_pos = Vector2(25.0, 0.0)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)

    ls = game.actors[0].get_component(LanderState)
    assert ls is not None
    ls.state = "landed"

    result = game.run(print_freq=0, max_steps=10)
    assert result["state"] == "landed"
    assert result["landing_offset"] == pytest.approx(25.0)


def test_state_transition_runs_once_per_frame_with_engine_enabled() -> None:
    level = _ShortLevel(stop_after_updates=999)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)
    game.engine_adapter._engine = _FakeEngine()

    calls = {"count": 0}
    original_update = game.state_transition_system.update

    def _counting_update(dt: float) -> None:
        calls["count"] += 1
        original_update(dt)

    game.state_transition_system.update = _counting_update
    result = game.run(print_freq=0, max_steps=3)
    assert result["updates"] == 3
    assert calls["count"] == 3


def test_physics_step_syncs_engine_mass_from_remaining_fuel() -> None:
    level = _ShortLevel(stop_after_updates=999)
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)
    fake_engine = _FakeEngine()
    game.engine_adapter._engine = fake_engine

    actor = game.actors[0]
    phys = actor.get_component(PhysicsState)
    tank = actor.get_component(FuelTank)
    cargo = actor.get_component(CargoHold)
    engine = actor.get_component(Engine)
    assert phys is not None
    assert tank is not None
    assert cargo is not None
    assert engine is not None

    phys.mass = 1.0
    tank.fuel = 100.0
    tank.density = 0.01
    cargo.cargo_mass = 2.0
    cargo.max_cargo_mass = 10.0
    engine.base_burn_rate = 6.0
    engine.thrust_level = 1.0
    engine.target_thrust = 1.0

    timers = LoopTimers(
        physics_dt=0.1,
        bot_dt=1.0,
        frame_dt=0.1,
        time_accum_physics=0.1,
    )
    game._update_physics_steps(timers)

    assert tank.fuel == pytest.approx(99.4)
    assert fake_engine.mass_updates
    assert fake_engine.mass_updates[-1] == pytest.approx(
        1.0 + tank.fuel * tank.density + cargo.cargo_mass
    )


def test_game_switches_active_actor_and_updates_alias() -> None:
    level = _TwoActorLevel()
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True)

    assert game.active_player_actor_uid == "actor_human"
    assert game.lander.uid == "actor_human"

    game._switch_active_actor()

    assert game.active_player_actor_uid == "actor_bot"
    assert game.lander.uid == "actor_bot"
    assert game.level.world.primary_actor_uid == "actor_bot"


def test_game_assigns_passed_bot_to_bot_role_actor() -> None:
    level = _TwoActorLevel()
    bot = _PassiveBot()
    game = LanderGame(level=level, bot=bot, headless=True)

    assert game.actor_bots == {"actor_bot": bot}


@pytest.mark.parametrize(
    "level_factory",
    [create_level_flat, create_level_mountains],
)
def test_level_presets_actor_spawns_are_above_local_terrain(level_factory) -> None:
    level = level_factory()
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=123)
    terrain = game.terrain

    actors = getattr(game.level.world, "actors", [])
    assert len(actors) == 1

    for actor in actors:
        trans = actor.get_component(Transform)
        geo = actor.get_component(LanderGeometry)
        assert trans is not None
        assert geo is not None

        half_w = max(geo.width * 0.5, 1.0)
        bottom = trans.pos.y - geo.height * 0.5
        sample_xs = (
            trans.pos.x - half_w,
            trans.pos.x,
            trans.pos.x + half_w,
        )
        for sx in sample_xs:
            assert bottom - terrain(sx) >= 10.0


@pytest.mark.parametrize(
    "level_factory",
    [create_level_flat, create_level_mountains],
)
def test_level_presets_assign_selected_bot_to_only_lander(level_factory) -> None:
    level = level_factory()
    bot = _PassiveBot()
    game = LanderGame(level=level, bot=bot, headless=True, seed=123)

    assert len(game.actors) == 1
    only_actor_uid = game.actors[0].uid
    assert game.actor_bots == {only_actor_uid: bot}


def test_level_presets_spawn_new_sites_as_player_reaches_frontier() -> None:
    level = create_level_flat()
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=123)

    initial_site_count = len(game.level.world.site_entities)
    lead = float(getattr(level, "dynamic_site_lead_distance", 2000.0))
    trans = game.lander.get_component(Transform)
    assert trans is not None

    trans.pos.x = 18000.0
    level.update(game, 1.0 / 60.0)
    after_right_count = len(game.level.world.site_entities)
    assert after_right_count > initial_site_count

    rightmost_x = max(
        _trans.pos.x
        for _trans in (
            site.get_component(Transform) for site in game.level.world.site_entities
        )
        if _trans is not None
    )
    assert rightmost_x >= trans.pos.x + lead

    trans.pos.x = -18000.0
    level.update(game, 1.0 / 60.0)
    after_left_count = len(game.level.world.site_entities)
    assert after_left_count > after_right_count

    leftmost_x = min(
        _trans.pos.x
        for _trans in (
            site.get_component(Transform) for site in game.level.world.site_entities
        )
        if _trans is not None
    )
    assert leftmost_x <= trans.pos.x - lead

    ecs_site_count = len(game.ecs_world.get_entities_with(LandingSite, Transform))
    assert ecs_site_count == after_left_count


def test_dynamic_sites_keep_radar_guidance_and_refuel_bridges() -> None:
    level = create_level_flat()
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=123)

    trans = game.lander.get_component(Transform)
    radar = game.lander.get_component(Radar)
    assert trans is not None
    assert radar is not None

    trans.pos.x = 70000.0
    level.update(game, 1.0 / 60.0)

    auto_right_sites: list[tuple[float, float]] = []
    for site in game.level.world.site_entities:
        if not site.uid.startswith("auto_site_"):
            continue
        site_trans = site.get_component(Transform)
        econ = site.get_component(LandingSiteEconomy)
        if site_trans is None or econ is None:
            continue
        if site_trans.pos.x <= 0.0:
            continue
        auto_right_sites.append((site_trans.pos.x, econ.fuel_price))

    auto_right_sites.sort(key=lambda row: row[0])
    assert len(auto_right_sites) >= 12

    gaps = [
        auto_right_sites[i + 1][0] - auto_right_sites[i][0]
        for i in range(len(auto_right_sites) - 1)
    ]
    cluster_spacing_max = float(getattr(level, "dynamic_cluster_spacing_max", 760.0))
    assert max(gaps) >= cluster_spacing_max * 2.0

    guidance_limit = radar.outer_range * float(
        getattr(level, "dynamic_radar_spacing_ratio", 0.85)
    )
    assert max(gaps) <= guidance_limit + 1e-6

    cheap_refuel_limit = float(getattr(level, "dynamic_refuel_price_max", 8.5))
    cheap_refuel_count = sum(
        1 for _, fuel_price in auto_right_sites if fuel_price <= cheap_refuel_limit + 1e-6
    )
    assert cheap_refuel_count >= 2


def test_level_registry_includes_named_presets() -> None:
    level_names = main_module.list_available_levels()
    assert "flat" in level_names
    assert "mountains" in level_names
    assert "plunge" in level_names
    assert "flare" in level_names
    assert "coast" in level_names
    assert "launch" in level_names
    assert {"drift", "transfer", "ferry"}.isdisjoint(set(level_names))
    assert "level_1" not in level_names


def test_cli_defaults_to_flat_when_omitted() -> None:
    parser = main_module._build_parser()
    args = parser.parse_args([])
    assert args.level_name == "flat"


def test_scenario_levels_reject_unknown_scenario_name() -> None:
    for level_name in ("plunge", "flare", "coast", "launch"):
        level = create_level_by_name(level_name)
        with pytest.raises(ValueError):
            level.set_eval_scenario("not_a_real_scenario_name")


def test_eval_level_is_deterministic_for_seed_and_scenario() -> None:
    level_a = create_level_by_name("plunge")
    level_a.set_eval_scenario("mid_normal")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=77)
    actor_a = game_a.actors[0]
    trans_a = actor_a.get_component(Transform)
    assert trans_a is not None
    site_a = level_a.world.site_entities[0].get_component(Transform)
    assert site_a is not None

    level_b = create_level_by_name("plunge")
    level_b.set_eval_scenario("mid_normal")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=77)
    actor_b = game_b.actors[0]
    trans_b = actor_b.get_component(Transform)
    assert trans_b is not None
    site_b = level_b.world.site_entities[0].get_component(Transform)
    assert site_b is not None

    assert trans_a.pos.x == trans_b.pos.x
    assert trans_a.pos.y == trans_b.pos.y
    assert site_a.pos.x == site_b.pos.x
    assert site_a.pos.y == site_b.pos.y


def test_plunge_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("plunge")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    assert set(list_scenarios()) == {
        "low_light",
        "low_normal",
        "low_heavy",
        "mid_light",
        "mid_normal",
        "mid_heavy",
        "high_light",
        "high_normal",
        "high_heavy",
    }


def test_plunge_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("plunge")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == [
        "low_normal",
        "mid_normal",
        "high_normal",
    ]


def test_plunge_cargo_scenario_applies_heavy_cargo_mass() -> None:
    level = create_level_by_name("plunge")
    level.set_eval_scenario("mid_heavy")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(4500.0)


def test_plunge_normal_weight_scenario_applies_half_cargo_mass() -> None:
    level = create_level_by_name("plunge")
    level.set_eval_scenario("mid_normal")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(2250.0)


def test_plunge_matrix_scenario_starts_with_zero_initial_velocity() -> None:
    level = create_level_by_name("plunge")
    level.set_eval_scenario("high_light")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert phys.vel.x == pytest.approx(0.0)
    assert phys.vel.y == pytest.approx(0.0)
    assert trans.rotation == pytest.approx(0.0)


def test_flare_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("flare")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    assert set(list_scenarios()) == {
        "shallower",
        "shallow",
        "mid",
        "steep",
        "steeper",
    }


def test_flare_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("flare")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == [
        "shallower",
        "mid",
        "steeper",
    ]


def test_flare_scenario_direction_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("flare")
    level_a.set_eval_scenario("mid")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=41)
    trans_a = game_a.actors[0].get_component(Transform)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert trans_a is not None
    assert phys_a is not None

    level_b = create_level_by_name("flare")
    level_b.set_eval_scenario("mid")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=41)
    trans_b = game_b.actors[0].get_component(Transform)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert trans_b is not None
    assert phys_b is not None

    assert trans_a.pos.x == pytest.approx(trans_b.pos.x)
    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_flare_scenario_applies_half_cargo_mass() -> None:
    level = create_level_by_name("flare")
    level.set_eval_scenario("mid")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(2250.0)


def test_flare_matrix_scenario_starts_on_center_hit_ballistic_path() -> None:
    level = create_level_by_name("flare")
    level.set_eval_scenario("steep")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=11)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert abs(phys.vel.x) > 1e-6
    assert phys.vel.y > 0.0
    target_pos = getattr(level, "eval_target_pos", Vector2(0.0, 0.0))
    assert trans.pos.x * phys.vel.x < 0.0  # Always moving toward target center.
    t_to_center = abs((target_pos.x - trans.pos.x) / phys.vel.x)
    assert t_to_center == pytest.approx(12.0)
    y_at_center = trans.pos.y + (phys.vel.y * t_to_center) - (
        0.5 * abs(GRAVITY) * t_to_center * t_to_center
    )
    assert y_at_center == pytest.approx(target_pos.y)
    retrograde_angle = math.atan2(-float(phys.vel.x), -float(phys.vel.y))
    angle_error = abs((retrograde_angle - float(trans.rotation) + math.pi) % (2.0 * math.pi) - math.pi)
    assert angle_error == pytest.approx(0.0, abs=1e-6)


def test_drift_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("coast")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    scenarios = set(list_scenarios())
    base = {
        "entry_shallow",
        "entry_shallow_trim",
        "entry_mid",
        "entry_mid_trim",
        "entry_mid_energy",
        "entry_steep",
        "entry_steep_energy",
        "entry_steep_stress",
    }
    assert base.issubset(scenarios)
    cargo_variants = {
        "entry_mid_energy",
        "entry_steep_stress",
    }
    for name in cargo_variants:
        assert f"{name}_cargo_high" in scenarios
        assert f"{name}_cargo_low" not in scenarios
    for name in (base - cargo_variants):
        assert f"{name}_cargo_high" not in scenarios
    assert len(scenarios) == len(base) + len(cargo_variants)


def test_drift_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("coast")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == [
        "entry_mid_trim",
        "entry_mid_energy",
        "entry_steep_stress",
    ]


def test_drift_scenario_sets_offset_and_horizontal_velocity() -> None:
    level = create_level_by_name("coast")
    level.set_eval_scenario("entry_mid")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert abs(trans.pos.x) > 0.0
    assert abs(phys.vel.x) > 0.0
    assert trans.pos.x * phys.vel.x < 0.0  # toward target from randomized side
    prograde_angle = math.atan2(float(phys.vel.x), float(phys.vel.y))
    angle_error = abs((prograde_angle - float(trans.rotation) + math.pi) % (2.0 * math.pi) - math.pi)
    assert angle_error == pytest.approx(0.0, abs=1e-6)


def test_drift_stress_scenario_starts_with_high_toward_speed() -> None:
    level = create_level_by_name("coast")
    level.set_eval_scenario("entry_steep_stress")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=9)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert abs(phys.vel.x) >= 20.0
    assert math.isfinite(phys.vel.y)
    assert trans.pos.x * phys.vel.x < 0.0


def test_drift_scenario_direction_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("coast")
    level_a.set_eval_scenario("entry_mid")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=19)
    trans_a = game_a.actors[0].get_component(Transform)
    assert trans_a is not None

    level_b = create_level_by_name("coast")
    level_b.set_eval_scenario("entry_mid")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=19)
    trans_b = game_b.actors[0].get_component(Transform)
    assert trans_b is not None

    assert trans_a.pos.x == pytest.approx(trans_b.pos.x)


def test_drift_correction_scenario_velocity_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("coast")
    level_a.set_eval_scenario("entry_mid_trim")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=23)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert phys_a is not None

    level_b = create_level_by_name("coast")
    level_b.set_eval_scenario("entry_mid_trim")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=23)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert phys_b is not None

    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_drift_correction_scenario_randomizes_error_direction_across_seeds() -> None:
    signs = set()
    projected_magnitudes = []
    for seed in range(40):
        level = create_level_by_name("coast")
        level.set_eval_scenario("entry_mid_energy")
        game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=seed)
        actor = game.actors[0]
        trans = actor.get_component(Transform)
        phys = actor.get_component(PhysicsState)
        assert trans is not None
        assert phys is not None

        alt = max(0.0, float(trans.pos.y))
        vy_up = float(phys.vel.y)
        disc = max(0.0, (vy_up * vy_up) + (2.0 * 9.8 * alt))
        t_fall = max(0.5, (vy_up + math.sqrt(disc)) / 9.8)
        projected_dx = float(trans.pos.x) + (float(phys.vel.x) * t_fall)
        projected_magnitudes.append(abs(projected_dx))
        if projected_dx > 1e-3:
            signs.add(1.0)
        elif projected_dx < -1e-3:
            signs.add(-1.0)

    assert signs == {-1.0, 1.0}
    assert min(projected_magnitudes) == pytest.approx(80.0, abs=0.75)
    assert max(projected_magnitudes) == pytest.approx(80.0, abs=0.75)


def test_drift_flat_scenario_starts_with_positive_vertical_velocity() -> None:
    level = create_level_by_name("coast")
    level.set_eval_scenario("entry_shallow")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=11)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert phys.vel.y > 0.0
    assert trans.pos.x * phys.vel.x < 0.0


def test_drift_flat_correction_velocity_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("coast")
    level_a.set_eval_scenario("entry_shallow_trim")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=37)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert phys_a is not None

    level_b = create_level_by_name("coast")
    level_b.set_eval_scenario("entry_shallow_trim")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=37)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert phys_b is not None

    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_drift_cargo_scenario_applies_heavy_cargo_mass() -> None:
    level = create_level_by_name("coast")
    level.set_eval_scenario("entry_steep_stress_cargo_high")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(4500.0)


def test_transfer_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("launch")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    scenarios = set(list_scenarios())
    base = {
        "air_mid",
        "air_long",
    }
    stress = {
        "air_mid_reverse",
    }
    heavy = {
        "air_long_heavy",
        "air_mid_reverse_heavy",
    }
    assert base.issubset(scenarios)
    assert stress.issubset(scenarios)
    assert heavy.issubset(scenarios)
    assert "air_low_long_climb" not in scenarios
    assert "air_high_long_climb" not in scenarios
    assert len(scenarios) == len(base) + len(stress) + len(heavy)


def test_transfer_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("launch")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == [
        "air_mid",
        "air_long",
        "air_mid_reverse",
        "air_long_heavy",
    ]


def test_transfer_scenario_direction_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("launch")
    level_a.set_eval_scenario("air_mid")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=31)
    trans_a = game_a.actors[0].get_component(Transform)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert trans_a is not None
    assert phys_a is not None

    level_b = create_level_by_name("launch")
    level_b.set_eval_scenario("air_mid")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=31)
    trans_b = game_b.actors[0].get_component(Transform)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert trans_b is not None
    assert phys_b is not None

    assert trans_a.pos.x == pytest.approx(trans_b.pos.x)
    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_transfer_reverse_scenario_starts_with_velocity_away_from_target() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("air_mid_reverse")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=17)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert trans.pos.x * phys.vel.x > 0.0


def test_transfer_cargo_scenario_applies_heavy_cargo_mass() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("air_long_heavy")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=11)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(3200.0)


def test_launch_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("launch")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    assert list_scenarios() == [
        "air_mid",
        "air_long",
        "air_mid_reverse",
        "air_long_heavy",
        "air_mid_reverse_heavy",
    ]


def test_launch_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("launch")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == [
        "air_mid",
        "air_long",
        "air_mid_reverse",
        "air_long_heavy",
    ]


def test_launch_scenario_direction_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("launch")
    level_a.set_eval_scenario("air_mid_reverse")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=29)
    trans_a = game_a.actors[0].get_component(Transform)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert trans_a is not None
    assert phys_a is not None

    level_b = create_level_by_name("launch")
    level_b.set_eval_scenario("air_mid_reverse")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=29)
    trans_b = game_b.actors[0].get_component(Transform)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert trans_b is not None
    assert phys_b is not None

    assert trans_a.pos.x == pytest.approx(trans_b.pos.x)
    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_parse_seed_spec_supports_ranges_and_lists() -> None:
    assert _parse_seed_spec("0-3") == [0, 1, 2, 3]
    assert _parse_seed_spec("3-1") == [3, 2, 1]
    assert _parse_seed_spec("1,3,5") == [1, 3, 5]
    assert _parse_seed_spec("0-2,2,4") == [0, 1, 2, 4]


def test_resolve_batch_plan_uses_quick_benchmark_cross_level_suite() -> None:
    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=False,
        print_freq=0,
        max_time=300.0,
        max_steps=12000,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds=None,
        batch_levels=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=True,
        batch_workers=1,
    )
    seeds, levels = _resolve_batch_plan(config)
    assert seeds == [0, 1, 2]
    assert levels == ["plunge", "flare", "coast", "launch"]


def test_eval_aggregate_summary_shape() -> None:
    records = [
        normalize_run_result(
            bot_name="plunge",
            level_name="plunge",
            scenario="alt_100",
            seed=0,
            result={
                "state": "landed",
                "time": 12.0,
                "landing_count": 1,
                "distance_flown": 240.0,
                "landing_offset": 6.5,
                "avg_speed": 20.0,
                "fuel_consumed": 15.0,
                "fuel_per_distance": 0.0625,
                "path_efficiency": 0.90,
            },
        ),
        normalize_run_result(
            bot_name="plunge",
            level_name="plunge",
            scenario="alt_100",
            seed=1,
            result={
                "state": "crashed",
                "time": 9.0,
                "crash_count": 1,
                "distance_flown": 180.0,
                "avg_speed": 20.0,
                "fuel_consumed": 25.0,
                "fuel_per_distance": 0.1389,
            },
        ),
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 2
    assert summary["landed"] == 1
    assert summary["crashed"] == 1
    assert "efficiency_success" in summary
    assert summary["efficiency_success"]["distance_flown"]["count"] == 1
    assert summary["efficiency_success"]["landing_offset"]["count"] == 1
    assert "efficiency_all" in summary
    assert summary["efficiency_all"]["distance_flown"]["count"] == 2
    assert summary["efficiency_all"]["fuel_remaining"]["count"] == 2
    assert "by_scenario" in summary
    assert "alt_100" in summary["by_scenario"]


def test_eval_aggregate_uses_explicit_success_for_non_landing_stage() -> None:
    records = [
        normalize_run_result(
            bot_name="launch",
            level_name="launch",
            scenario="air_mid",
            seed=3,
            result={
                "state": "flying",
                "time": 6.0,
                "success": True,
                "failure_mode": "none",
                "eval_mode": "focused",
                "eval_phase": "launch_setup",
                "launch_handoff_time": 6.0,
                "launch_handoff_impact_error": 4.0,
                "launch_setup_distance": 180.0,
                "launch_setup_fuel_consumed": 12.0,
            },
        )
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 1
    assert summary["successes"] == 1
    assert summary["landed"] == 0
    assert summary["success_rate"] == pytest.approx(1.0)
    assert summary["by_scenario"]["air_mid"]["success_rate"] == pytest.approx(1.0)


def test_print_batch_summary_includes_per_scenario_efficiency_means(capsys) -> None:
    summary = {
        "runs": 1,
        "landed": 1,
        "crashed": 0,
        "out_of_fuel": 0,
        "flying": 0,
        "other": 0,
        "success_rate": 1.0,
        "efficiency_success": {},
        "efficiency_all": {},
        "by_scenario": {
            "alt_100": {
                "runs": 1,
                "landed": 1,
                "crashed": 0,
                "out_of_fuel": 0,
                "flying": 0,
                "other": 0,
                "success_rate": 1.0,
                "efficiency_success": {
                    "fuel_consumed": {"count": 1, "mean": 8.5, "median": 8.5, "p90": 8.5},
                    "time": {"count": 1, "mean": 22.0, "median": 22.0, "p90": 22.0},
                },
                "efficiency_all": {},
            }
        },
    }
    main_module._print_batch_summary(summary, failures=[], json_path=None, csv_path=None)
    out = capsys.readouterr().out
    assert "efficiency_success: fuel_mean=8.50 time_mean=22.00" in out


def test_parse_args_defaults_to_quiet_batch_output() -> None:
    args = argparse.Namespace(
        level_name="plunge",
        bot="plunge",
        bot_behavior=None,
        headless=True,
        batch=False,
        freq=None,
        steps=None,
        time=None,
        plot=None,
        stop_on_crash=False,
        stop_on_out_of_fuel=False,
        stop_on_first_land=False,
        seed=None,
        scenario=None,
        lander=None,
        batch_seeds="0-1",
        batch_levels=None,
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    config = _parse_args(args)
    assert config.print_freq == 0


def test_parse_args_accepts_scenario_options() -> None:
    args = argparse.Namespace(
        level_name="plunge",
        bot="plunge",
        bot_behavior="balanced",
        headless=True,
        batch=False,
        freq=None,
        steps=None,
        time=None,
        plot=None,
        stop_on_crash=False,
        stop_on_out_of_fuel=False,
        stop_on_first_land=False,
        seed=None,
        scenario="mid_normal",
        lander=None,
        batch_seeds=None,
        batch_levels=None,
        batch_scenarios="mid_normal,high_heavy",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    config = _parse_args(args)
    assert config.scenario_name == "mid_normal"
    assert config.batch_scenarios == "mid_normal,high_heavy"
    assert config.bot_behavior == "balanced"


def test_parse_args_accepts_eval_mode() -> None:
    args = argparse.Namespace(
        level_name="transfer",
        bot="transfer",
        bot_behavior=None,
        headless=True,
        batch=False,
        freq=None,
        steps=None,
        time=None,
        plot=None,
        stop_on_crash=False,
        stop_on_out_of_fuel=False,
        stop_on_first_land=False,
        eval_mode="full",
        seed=None,
        scenario=None,
        lander=None,
        batch_seeds=None,
        batch_levels=None,
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    config = _parse_args(args)
    assert config.eval_mode == "full"


def test_configure_level_rejects_explicit_eval_mode_for_unsupported_level() -> None:
    level = create_level_flat()
    config = RunConfig(
        level_name="flat",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=False,
        print_freq=0,
        max_time=300.0,
        max_steps=200,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=0,
        lander_name=None,
        batch_seeds=None,
        batch_levels=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
        eval_mode="focused",
    )
    with pytest.raises(ValueError, match="does not support --eval-mode"):
        main_module._configure_level(level, config)


def test_drift_focused_eval_stops_on_handoff_and_marks_success(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {
            "kind": "coast",
            "handoff_done": True,
            "projected_dx": 2.5,
            "impact_x": 4.2,
            "target_x": 3.5,
            "on_track": True,
            "inside_target": True,
            "speed_ready": True,
            "descending": True,
            "t_fall_ready": True,
            "sensor_used": True,
            "vx_err": 1.4,
            "t_fall": 4.1,
            "x": 8.0,
            "y": 130.0,
            "dx": -2.3,
            "vx": -9.0,
            "vy_up": -2.2,
            "speed": 9.3,
            "horizontal_speed": 9.0,
            "altitude": 130.0,
            "angle_rad": 0.12,
        }

    level = create_level_by_name("coast")
    level.set_eval_mode("focused")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_coast_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=14)
    result = game.run(print_freq=0, max_steps=60)
    assert result["eval_mode"] == "focused"
    assert result["eval_phase"] == "coast_setup"
    assert result["success"] is True
    assert result["failure_mode"] == "none"
    assert result["coast_handoff_done"] is True
    assert result["state"] == "flying"


def test_drift_full_eval_does_not_end_on_handoff(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {"kind": "coast", "handoff_done": True}

    level = create_level_by_name("coast")
    level.set_eval_mode("full")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_coast_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=18)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game) is False


def test_drift_focused_eval_fails_when_handoff_projection_is_out_of_bounds(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {
            "kind": "coast",
            "handoff_done": True,
            "projected_dx": 65.0,
            "inside_target": False,
            "on_track": False,
            "speed_ready": True,
            "descending": True,
            "t_fall_ready": True,
            "sensor_used": True,
        }

    level = create_level_by_name("coast")
    level.set_eval_mode("focused")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_coast_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=33)
    result = game.run(print_freq=0, max_steps=60)
    assert result["eval_mode"] == "focused"
    assert result["eval_phase"] == "coast_setup"
    assert result["coast_handoff_done"] is True
    assert result["success"] is False
    assert result["failure_mode"] == "projection_out_of_bounds"


def test_transfer_focused_eval_stops_on_handoff_and_marks_success(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {
            "kind": "launch",
            "handoff_done": True,
            "projected_dx": 2.0,
            "impact_x": 7.0,
            "target_x": 3.0,
            "impact_error": 4.0,
            "current_impact_x": 3.4,
            "current_target_x": 3.0,
            "current_impact_error": 0.4,
            "on_track": True,
            "speed_ready": True,
            "not_falling_short": True,
            "centered": True,
            "inside_target": True,
        }

    level = create_level_by_name("launch")
    level.set_eval_mode("focused")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_launch_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=19)
    result = game.run(print_freq=0, max_steps=60)
    assert result["eval_mode"] == "focused"
    assert result["eval_phase"] == "launch_setup"
    assert result["success"] is True
    assert result["failure_mode"] == "none"
    assert result["launch_handoff_done"] is True
    assert result["launch_handoff_impact_error"] == pytest.approx(0.4)
    assert result["launch_handoff_planned_impact_error"] == pytest.approx(4.0)
    assert "launch_handoff_current_impact_error" not in result
    assert result["state"] == "flying"


def test_transfer_full_eval_does_not_end_on_handoff(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {"kind": "launch", "handoff_done": True}

    level = create_level_by_name("launch")
    level.set_eval_mode("full")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_launch_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=23)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game) is False


def test_transfer_focused_eval_without_handoff_keeps_handoff_angle_empty(
    monkeypatch,
) -> None:
    def _no_handoff_snapshot(_game):
        return {"kind": "launch", "handoff_done": False}

    level = create_level_by_name("launch")
    level.set_eval_mode("focused")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_launch_snapshot",
        staticmethod(_no_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=31)
    result = game.run(print_freq=0, max_steps=1)
    assert result["eval_mode"] == "focused"
    assert result["launch_handoff_done"] is False
    assert result["launch_handoff_abs_angle_deg"] is None


def test_ferry_focused_eval_stops_on_handoff_and_marks_success(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {
            "kind": "launch",
            "handoff_done": True,
            "projected_dx": 3.0,
            "impact_x": 8.0,
            "target_x": 5.0,
            "impact_error": 3.0,
            "current_impact_x": 5.1,
            "current_target_x": 5.0,
            "current_impact_error": 0.1,
            "on_track": True,
            "speed_ready": True,
            "not_falling_short": True,
            "centered": True,
            "inside_target": True,
        }

    level = create_level_by_name("launch")
    level.set_eval_mode("focused")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_launch_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=21)
    result = game.run(print_freq=0, max_steps=60)
    assert result["eval_mode"] == "focused"
    assert result["eval_phase"] == "launch_setup"
    assert result["success"] is True
    assert result["failure_mode"] == "none"
    assert result["launch_handoff_done"] is True
    assert result["launch_handoff_impact_error"] == pytest.approx(0.1)
    assert result["state"] == "flying"


def test_ferry_full_eval_does_not_end_on_handoff(monkeypatch) -> None:
    def _handoff_snapshot(_game):
        return {"kind": "launch", "handoff_done": True}

    level = create_level_by_name("launch")
    level.set_eval_mode("full")
    monkeypatch.setattr(
        level.__class__,
        "_resolve_launch_snapshot",
        staticmethod(_handoff_snapshot),
    )
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=25)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game) is False


def test_hud_altitude_matches_passive_sensor_clearance_convention() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    hud = HudOverlay(font=None, screen=None)

    lines = hud._build_info_lines(level, actor)
    alt_line = next(line for line in lines if line.startswith("ALT: "))

    # Transform y=100, terrain y=20, half-height=4 => clearance is 76.
    assert "ALT: 76.0 m" in alt_line


def test_hud_includes_mass_breakdown_lines() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    hud = HudOverlay(font=None, screen=None)

    lines = hud._build_info_lines(level, actor)
    mass_line = next(line for line in lines if line.startswith("MASS: "))
    assert " t" in mass_line
    assert "dry " in mass_line
    assert "fuel " in mass_line
    assert "cargo " in mass_line


def test_hud_includes_acceleration_and_twr_lines() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    hud = HudOverlay(font=None, screen=None)

    lines = hud._build_info_lines(level, actor)
    assert any(line.startswith("ACC: ") for line in lines)
    assert any(line.startswith("TWR N/B: ") for line in lines)


def test_hud_thrust_line_turns_red_in_overdrive() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    engine = actor.get_component(Engine)
    assert engine is not None
    engine.thrust_level = 1.2
    engine.target_thrust = 1.3
    hud = HudOverlay(font=None, screen=None)

    specs = hud._build_info_line_specs(level, actor)
    thrust_entry = next(entry for entry in specs if entry[0].startswith("THRUST:"))
    assert thrust_entry[1] == (255, 90, 90)
    assert "[OD]" in thrust_entry[0]


def test_hud_suppresses_negative_zero_jitter() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    phys = actor.get_component(PhysicsState)
    trans = actor.get_component(Transform)
    eng = actor.get_component(Engine)
    assert phys is not None
    assert trans is not None
    assert eng is not None
    phys.vel = Vector2(-0.01, -0.01)
    phys.acc = Vector2(-0.001, -0.001)
    trans.rotation = -0.01
    eng.target_angle = -0.01
    hud = HudOverlay(font=None, screen=None)

    lines = hud._build_info_lines(level, actor)
    text = " | ".join(lines)
    assert "-0.0" not in text
    assert "-0.00" not in text


def test_headless_stats_altitude_matches_passive_sensor_clearance_convention() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    stats = _build_headless_stats(actor, lambda _x: 20.0)

    # Transform y=100, terrain y=20, half-height=4 => clearance is 76.
    assert "alt:  76.0" in stats


def test_run_batch_exit_code_uses_success_not_landed(monkeypatch) -> None:
    def _fake_plan(_config):
        return [0], ["transfer"]

    def _fake_run_once_record(config, *, seed, level_name, eval_scenario_name=None):
        _ = config, seed, level_name, eval_scenario_name
        return {
            "seed": 0,
            "state": "flying",
            "success": True,
        }

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)
    monkeypatch.setattr(main_module, "_run_once_record", _fake_run_once_record)
    monkeypatch.setattr(main_module.os, "cpu_count", lambda: 1)

    config = RunConfig(
        level_name="transfer",
        bot_name="transfer",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds="0",
        batch_levels="transfer",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    assert _run_batch(config) == 0


def test_run_batch_falls_back_when_parallel_executor_raises_runtime_error(
    monkeypatch, capsys
) -> None:
    class _FailingExecutor:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs
            raise RuntimeError("boom")

    def _fake_plan(_config):
        return [0, 1], ["plunge"]

    def _fake_run_once_record(config, *, seed, level_name, eval_scenario_name=None):
        _ = config, level_name
        _ = eval_scenario_name
        return {
            "seed": seed,
            "state": "landed",
            "success": True,
        }

    monkeypatch.setattr(main_module, "ProcessPoolExecutor", _FailingExecutor)
    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)
    monkeypatch.setattr(main_module, "_run_once_record", _fake_run_once_record)
    monkeypatch.setattr(main_module.os, "cpu_count", lambda: 8)

    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds="0-1",
        batch_levels="plunge",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )
    exit_code = _run_batch(config)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Batch workers unavailable (RuntimeError" in out


def test_run_batch_honors_batch_scenarios_filter(monkeypatch) -> None:
    seen_scenarios: list[str | None] = []

    def _fake_plan(_config):
        return [0], ["plunge"]

    def _fake_run_once_record(config, *, seed, level_name, eval_scenario_name=None):
        _ = config, seed, level_name
        seen_scenarios.append(eval_scenario_name)
        return {
            "seed": seed,
            "state": "landed",
            "success": True,
        }

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)
    monkeypatch.setattr(main_module, "_run_once_record", _fake_run_once_record)
    monkeypatch.setattr(main_module.os, "cpu_count", lambda: 1)

    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds="0",
        batch_levels="plunge",
        batch_scenarios="mid_normal,high_heavy",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    exit_code = _run_batch(config)
    assert exit_code == 0
    assert seen_scenarios == ["mid_normal", "high_heavy"]


def test_run_batch_quick_benchmark_uses_cross_level_core_suite(monkeypatch) -> None:
    seen_runs: list[tuple[int | None, str, str | None]] = []

    def _fake_run_once_record(config, *, seed, level_name, eval_scenario_name=None):
        _ = config
        seen_runs.append((seed, level_name, eval_scenario_name))
        return {
            "seed": seed,
            "state": "landed",
            "success": True,
        }

    monkeypatch.setattr(main_module, "_run_once_record", _fake_run_once_record)
    monkeypatch.setattr(main_module.os, "cpu_count", lambda: 1)

    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds=None,
        batch_levels=None,
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=True,
        batch_workers=1,
    )
    exit_code = _run_batch(config)
    assert exit_code == 0

    plunge_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "plunge" and scenario is not None
        }
    )
    flare_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "flare" and scenario is not None
        }
    )
    coast_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "coast" and scenario is not None
        }
    )
    launch_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "launch" and scenario is not None
        }
    )
    assert plunge_scenarios == [
        "high_normal",
        "low_normal",
        "mid_normal",
    ]
    assert flare_scenarios == [
        "mid",
        "shallower",
        "steeper",
    ]
    assert coast_scenarios == [
        "entry_mid_energy",
        "entry_mid_trim",
        "entry_steep_stress",
    ]
    assert launch_scenarios == [
        "air_long",
        "air_long_heavy",
        "air_mid",
        "air_mid_reverse",
    ]
    assert len(seen_runs) == 39  # 3 seeds x 13 quick scenarios


def test_run_batch_rejects_empty_seed_plan(monkeypatch) -> None:
    def _fake_plan(_config):
        return [], ["plunge"]

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)

    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds="",
        batch_levels="plunge",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )

    with pytest.raises(ValueError, match="resolved no seeds"):
        _run_batch(config)


def test_run_batch_rejects_empty_level_plan(monkeypatch) -> None:
    def _fake_plan(_config):
        return [0, 1], []

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)

    config = RunConfig(
        level_name="plunge",
        bot_name="plunge",
        bot_behavior=None,
        headless=True,
        batch=True,
        print_freq=0,
        max_time=300.0,
        max_steps=100,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds="0-1",
        batch_levels="",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )

    with pytest.raises(ValueError, match="resolved no levels"):
        _run_batch(config)
