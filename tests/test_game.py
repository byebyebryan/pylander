from __future__ import annotations

import argparse
import math

import main as main_module
import pytest
from bots._descent_core import GuidanceTargets
from bots._drift_core import (
    DriftCourseConfig,
    apply_drift_guidance,
    cap_low_altitude_angle,
    lateral_tracking_command,
    resolve_drift_behavior,
)
from bots import create_bot, list_available_bots
from bots.descent import DescentBot
from core.eval import aggregate_eval_records, normalize_run_result
from core.bot import Bot, BotAction, PassiveSensors
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
from game import LanderGame, LoopTimers, _build_headless_stats
from main import RunConfig, _parse_args, _parse_seed_spec, _resolve_batch_plan, _run_batch
from levels import create_level as create_level_by_name
from levels.flat import create_level as create_level_flat
from levels.mountains import create_level as create_level_mountains
from levels.scenario_common import validate_scenario_recoverability
from ui.hud import HudOverlay


def test_bot_registry_exposes_expected_bots() -> None:
    bots = list_available_bots()
    assert "descent" in bots
    assert "drift" in bots
    assert "_descent_core" not in bots
    assert "_drift_core" not in bots
    assert "descent_speed" not in bots
    assert "descent_econ" not in bots
    assert "turtle" not in bots
    assert {"drop", "plunge", "ferry"}.isdisjoint(set(bots))
    descent_bot = create_bot("descent")
    drift_bot = create_bot("drift")
    assert descent_bot.__class__.__name__ == "DescentBot"
    assert drift_bot.__class__.__name__ == "DriftBot"


def test_descent_bot_engine_profile_fallback_uses_realistic_defaults() -> None:
    bot = DescentBot()
    max_power, min_throttle, max_throttle, ramp_up = bot._engine_profile()
    assert max_power == pytest.approx(230000.0)
    assert min_throttle == pytest.approx(0.25)
    assert max_throttle == pytest.approx(1.6)
    assert ramp_up == pytest.approx(1.1)


def test_descent_econ_behavior_blocks_overdrive_when_fuel_margin_is_low() -> None:
    bot = DescentBot(behavior="econ")
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


def test_descent_speed_behavior_status_prefix_is_distinct() -> None:
    bot = DescentBot(behavior="speed")
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
    assert action.status.startswith("descent_speed:")


def test_descent_speed_behavior_can_use_overdrive_outside_terminal_mode() -> None:
    bot = DescentBot(behavior="speed")
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
    assert bot._can_use_overdrive(passive, vertical_mode="flare", alt=30.0)


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
    assert adjusted.phase == "drift"
    assert adjusted.vertical_mode == "drift_coast"
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
    assert adjusted.phase == "drift"
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
    assert adjusted_on_target.vx_sp == pytest.approx(guidance.vx_sp)

    adjusted_off_target = apply_drift_guidance(guidance, cfg, vx=0.0, vy_up=0.0)
    assert adjusted_off_target.vertical_mode == "drift_coast"
    assert abs(adjusted_off_target.vx_sp) >= cfg.correction_vx_min


def test_apply_drift_guidance_forces_thrust_backed_correction_for_high_vx_on_track() -> None:
    _, _, cfg = resolve_drift_behavior("drift")
    guidance = GuidanceTargets(
        phase="coast",
        vertical_mode="coast",
        vx_sp=0.8,
        vy_sp=-1.4,
        dx=400.0,
        alt=600.0,
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
    assert adjusted.vertical_mode == "drift_coast"


def test_resolve_drift_behavior_exposes_single_unified_profile() -> None:
    key, _, _ = resolve_drift_behavior("drift")
    assert key == "drift"
    with pytest.raises(ValueError):
        resolve_drift_behavior("accuracy")


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
    on_track_vx = guidance.dx / t_fall
    adjusted = apply_drift_guidance(guidance, cfg, vx=on_track_vx, vy_up=0.0)
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
    assert "drift" in level_names
    assert "level_1" not in level_names


def test_cli_defaults_to_flat_when_omitted() -> None:
    parser = main_module._build_parser()
    args = parser.parse_args([])
    assert args.level_name == "flat"


def test_eval_level_is_deterministic_for_seed_and_scenario() -> None:
    level_a = create_level_by_name("drop")
    level_a.set_eval_scenario("alt_400")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=77)
    actor_a = game_a.actors[0]
    trans_a = actor_a.get_component(Transform)
    assert trans_a is not None
    site_a = level_a.world.site_entities[0].get_component(Transform)
    assert site_a is not None

    level_b = create_level_by_name("drop")
    level_b.set_eval_scenario("alt_400")
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


def test_descent_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("drop")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    scenarios = set(list_scenarios())
    base = {
        "alt_100",
        "alt_400",
        "alt_1600",
        "speed_low",
        "speed_high",
        "upward_low",
    }
    assert base.issubset(scenarios)
    cargo_variants = {"alt_400", "speed_high", "upward_low"}
    for name in cargo_variants:
        assert f"{name}_cargo_low" in scenarios
        assert f"{name}_cargo_high" in scenarios
    for name in (base - cargo_variants):
        assert f"{name}_cargo_low" not in scenarios
        assert f"{name}_cargo_high" not in scenarios
    assert len(scenarios) == len(base) + (len(cargo_variants) * 2)


def test_descent_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("drop")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == ["alt_400", "speed_high", "upward_low"]


def test_descent_cargo_scenario_applies_heavy_cargo_mass() -> None:
    level = create_level_by_name("drop")
    level.set_eval_scenario("alt_400_cargo_high")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(4500.0)


def test_descent_upward_scenario_starts_with_positive_vertical_velocity() -> None:
    level = create_level_by_name("drop")
    level.set_eval_scenario("upward_low")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    phys = actor.get_component(PhysicsState)
    assert phys is not None
    assert phys.vel.y > 0.0


def test_descent_speed_high_scenario_sets_recoverable_initial_velocity() -> None:
    level = create_level_by_name("drop")
    level.set_eval_scenario("speed_high")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    phys = actor.get_component(PhysicsState)
    tank = actor.get_component(FuelTank)
    cargo = actor.get_component(CargoHold)
    engine = actor.get_component(Engine)
    assert phys is not None
    assert tank is not None
    assert cargo is not None
    assert engine is not None
    assert phys.vel.y < 0.0

    cargo_mass = max(0.0, min(cargo.cargo_mass, cargo.max_cargo_mass))
    total_mass = max(0.5, phys.mass + tank.fuel * tank.density + cargo_mass)
    max_up_acc = ((engine.max_power * engine.max_thrust) / total_mass) - 9.8
    assert max_up_acc > 0.0
    stop_distance = (abs(phys.vel.y) ** 2) / (2.0 * max_up_acc)
    assert stop_distance < 320.0 * 0.82


def test_drift_level_lists_expected_scenarios() -> None:
    level = create_level_by_name("drift")
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    assert callable(list_scenarios)
    scenarios = set(list_scenarios())
    base = {
        "glide_short",
        "glide_short_correction",
        "glide_mid",
        "glide_mid_correction",
        "glide_long",
        "glide_long_correction",
        "glide_long_stress_correction",
        "climb",
        "climb_correction",
        "climb_stress_correction",
    }
    assert base.issubset(scenarios)
    cargo_variants = {
        "glide_mid_correction",
        "glide_long_correction",
        "glide_long_stress_correction",
    }
    for name in cargo_variants:
        assert f"{name}_cargo_high" in scenarios
        assert f"{name}_cargo_low" not in scenarios
    for name in (base - cargo_variants):
        assert f"{name}_cargo_high" not in scenarios
    assert len(scenarios) == len(base) + len(cargo_variants)


def test_drift_level_lists_expected_quick_benchmark_scenarios() -> None:
    level = create_level_by_name("drift")
    list_quick_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
    assert callable(list_quick_scenarios)
    assert list_quick_scenarios() == ["glide_mid", "glide_long_stress_correction"]


def test_drift_scenario_sets_offset_and_horizontal_velocity() -> None:
    level = create_level_by_name("drift")
    level.set_eval_scenario("glide_mid")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert abs(trans.pos.x) > 0.0
    assert abs(phys.vel.x) > 0.0
    assert trans.pos.x * phys.vel.x < 0.0  # toward target from randomized side


def test_drift_scenario_direction_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("drift")
    level_a.set_eval_scenario("glide_mid")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=19)
    trans_a = game_a.actors[0].get_component(Transform)
    assert trans_a is not None

    level_b = create_level_by_name("drift")
    level_b.set_eval_scenario("glide_mid")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=19)
    trans_b = game_b.actors[0].get_component(Transform)
    assert trans_b is not None

    assert trans_a.pos.x == pytest.approx(trans_b.pos.x)


def test_drift_correction_scenario_velocity_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("drift")
    level_a.set_eval_scenario("glide_mid_correction")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=23)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert phys_a is not None

    level_b = create_level_by_name("drift")
    level_b.set_eval_scenario("glide_mid_correction")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=23)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert phys_b is not None

    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)


def test_drift_correction_scenario_randomizes_error_direction_across_seeds() -> None:
    signs = set()
    for seed in range(40):
        level = create_level_by_name("drift")
        level.set_eval_scenario("climb_correction")
        game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=seed)
        actor = game.actors[0]
        trans = actor.get_component(Transform)
        phys = actor.get_component(PhysicsState)
        assert trans is not None
        assert phys is not None

        target_pos = getattr(level, "eval_target_pos", Vector2(0.0, 0.0))
        alt = max(0.0, float(trans.pos.y - target_pos.y))
        disc = max(0.0, (phys.vel.y * phys.vel.y) + (2.0 * 9.8 * alt))
        t_fall = max(0.5, (phys.vel.y + math.sqrt(disc)) / 9.8)
        ballistic_vx = (float(target_pos.x) - float(trans.pos.x)) / t_fall
        vx_error = phys.vel.x - ballistic_vx
        if vx_error > 1e-6:
            signs.add(1.0)
        elif vx_error < -1e-6:
            signs.add(-1.0)

    assert signs == {-1.0, 1.0}


def test_drift_climb_scenario_starts_with_positive_vertical_velocity() -> None:
    level = create_level_by_name("drift")
    level.set_eval_scenario("climb")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=11)
    actor = game.actors[0]
    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    assert trans is not None
    assert phys is not None
    assert phys.vel.y > 0.0
    assert trans.pos.x * phys.vel.x < 0.0


def test_drift_climb_correction_velocity_is_deterministic_for_seed() -> None:
    level_a = create_level_by_name("drift")
    level_a.set_eval_scenario("climb_correction")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=37)
    phys_a = game_a.actors[0].get_component(PhysicsState)
    assert phys_a is not None

    level_b = create_level_by_name("drift")
    level_b.set_eval_scenario("climb_correction")
    game_b = LanderGame(level=level_b, bot=_PassiveBot(), headless=True, seed=37)
    phys_b = game_b.actors[0].get_component(PhysicsState)
    assert phys_b is not None

    assert phys_a.vel.x == pytest.approx(phys_b.vel.x)
    assert phys_a.vel.y == pytest.approx(phys_b.vel.y)


def test_drift_cargo_scenario_applies_heavy_cargo_mass() -> None:
    level = create_level_by_name("drift")
    level.set_eval_scenario("glide_long_stress_correction_cargo_high")
    game = LanderGame(level=level, bot=_PassiveBot(), headless=True, seed=7)
    actor = game.actors[0]
    cargo = actor.get_component(CargoHold)
    assert cargo is not None
    assert cargo.cargo_mass == pytest.approx(4500.0)


def test_parse_seed_spec_supports_ranges_and_lists() -> None:
    assert _parse_seed_spec("0-3") == [0, 1, 2, 3]
    assert _parse_seed_spec("3-1") == [3, 2, 1]
    assert _parse_seed_spec("1,3,5") == [1, 3, 5]
    assert _parse_seed_spec("0-2,2,4") == [0, 1, 2, 4]


def test_resolve_batch_plan_uses_quick_benchmark_cross_level_suite() -> None:
    config = RunConfig(
        level_name="drop",
        bot_name="descent",
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
    assert levels == ["drop", "drift"]


def test_eval_aggregate_summary_shape() -> None:
    records = [
        normalize_run_result(
            bot_name="descent",
            level_name="drop",
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
            bot_name="descent",
            level_name="drop",
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
        level_name="drop",
        bot="descent",
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
        level_name="drop",
        bot="descent",
        bot_behavior="speed",
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
        scenario="alt_400",
        lander=None,
        batch_seeds=None,
        batch_levels=None,
        batch_scenarios="alt_400,speed_high",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    config = _parse_args(args)
    assert config.scenario_name == "alt_400"
    assert config.batch_scenarios == "alt_400,speed_high"
    assert config.bot_behavior == "speed"


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


def test_run_batch_falls_back_when_parallel_executor_raises_runtime_error(
    monkeypatch, capsys
) -> None:
    class _FailingExecutor:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs
            raise RuntimeError("boom")

    def _fake_plan(_config):
        return [0, 1], ["drop"]

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
        level_name="drop",
        bot_name="descent",
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
        batch_levels="drop",
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
        return [0], ["drop"]

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
        level_name="drop",
        bot_name="descent",
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
        batch_levels="drop",
        batch_scenarios="alt_400,speed_high",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    exit_code = _run_batch(config)
    assert exit_code == 0
    assert seen_scenarios == ["alt_400", "speed_high"]


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
        level_name="drop",
        bot_name="descent",
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

    drop_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "drop" and scenario is not None
        }
    )
    drift_scenarios = sorted(
        {
            scenario
            for _seed, level_name, scenario in seen_runs
            if level_name == "drift" and scenario is not None
        }
    )
    assert drop_scenarios == ["alt_400", "speed_high", "upward_low"]
    assert drift_scenarios == ["glide_long_stress_correction", "glide_mid"]
    assert len(seen_runs) == 15  # 3 seeds x 5 quick scenarios


def test_run_batch_rejects_empty_seed_plan(monkeypatch) -> None:
    def _fake_plan(_config):
        return [], ["drop"]

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)

    config = RunConfig(
        level_name="drop",
        bot_name="descent",
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
        batch_levels="drop",
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
        level_name="drop",
        bot_name="descent",
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
