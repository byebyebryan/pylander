from __future__ import annotations

import argparse

import main as main_module
import pytest
from bots import create_bot, list_available_bots
from core.eval import aggregate_eval_records, normalize_run_result
from core.bot import Bot, BotAction
from core.components import (
    ActorControlRole,
    LanderGeometry,
    LanderState,
    PlayerControlled,
    PlayerSelectable,
    Transform,
)
from core.landing_sites import LandingSiteSurfaceModel
from core.maths import Vector2
from core.lander import Lander
from core.level import Level, LevelWorld
from game import LanderGame, _build_headless_stats
from main import RunConfig, _parse_args, _parse_seed_spec, _resolve_batch_plan, _run_batch
from levels import create_level as create_level_by_name
from levels.level_flat import create_level as create_level_flat
from levels.level_mountains import create_level as create_level_mountains
from ui.hud import HudOverlay


def test_bot_registry_only_exposes_turtle() -> None:
    bots = list_available_bots()
    assert bots == ["turtle"]
    turtle_bot = create_bot("turtle")
    assert turtle_bot.__class__.__name__ == "TurtleBot"


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

    def set_lander_mass(self, _mass: float) -> None:
        pass

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

        half_w = geo.width * 0.5
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


def test_level_registry_includes_named_presets() -> None:
    level_names = main_module.list_available_levels()
    assert "level_flat" in level_names
    assert "level_mountains" in level_names
    assert "level_1" not in level_names


def test_cli_defaults_to_level_flat_when_omitted() -> None:
    parser = main_module._build_parser()
    args = parser.parse_args([])
    assert args.level_name == "level_flat"


def test_eval_level_is_deterministic_for_seed_and_scenario() -> None:
    level_a = create_level_by_name("level_eval")
    setattr(level_a, "eval_scenario", "climb_to_target")
    game_a = LanderGame(level=level_a, bot=_PassiveBot(), headless=True, seed=77)
    actor_a = game_a.actors[0]
    trans_a = actor_a.get_component(Transform)
    assert trans_a is not None
    site_a = level_a.world.site_entities[0].get_component(Transform)
    assert site_a is not None

    level_b = create_level_by_name("level_eval")
    setattr(level_b, "eval_scenario", "climb_to_target")
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


def test_parse_seed_spec_supports_ranges_and_lists() -> None:
    assert _parse_seed_spec("0-3") == [0, 1, 2, 3]
    assert _parse_seed_spec("3-1") == [3, 2, 1]
    assert _parse_seed_spec("1,3,5") == [1, 3, 5]
    assert _parse_seed_spec("0-2,2,4") == [0, 1, 2, 4]


def test_resolve_batch_plan_uses_quick_benchmark_for_eval_level() -> None:
    config = RunConfig(
        level_name="level_eval",
        bot_name="turtle",
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
        eval_scenario=None,
        batch_seeds=None,
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=True,
        batch_workers=1,
    )
    seeds, scenarios = _resolve_batch_plan(config)
    assert seeds == [0, 1, 2]
    assert scenarios == [
        "spawn_above_target",
        "increase_horizontal_distance",
        "climb_to_target",
        "complex_terrain_vertical_features",
    ]


def test_eval_aggregate_summary_shape() -> None:
    records = [
        normalize_run_result(
            bot_name="turtle",
            level_name="level_eval",
            scenario="spawn_above_target",
            seed=0,
            result={"state": "landed", "time": 12.0, "landing_count": 1},
        ),
        normalize_run_result(
            bot_name="turtle",
            level_name="level_eval",
            scenario="spawn_above_target",
            seed=1,
            result={"state": "crashed", "time": 9.0, "crash_count": 1},
        ),
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 2
    assert summary["landed"] == 1
    assert summary["crashed"] == 1
    assert "by_scenario" in summary
    assert "spawn_above_target" in summary["by_scenario"]


def test_parse_args_defaults_to_quiet_batch_output() -> None:
    args = argparse.Namespace(
        level_name="level_eval",
        bot_name="turtle",
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
        lander=None,
        eval_scenario=None,
        batch_seeds="0-1",
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=1,
    )
    config = _parse_args(args)
    assert config.print_freq == 0


def test_hud_altitude_matches_passive_sensor_clearance_convention() -> None:
    actor = Lander(start_pos=Vector2(0.0, 100.0))
    level = _FixedTerrainLevel()
    hud = HudOverlay(font=None, screen=None)

    lines = hud._build_info_lines(level, actor)
    alt_line = next(line for line in lines if line.startswith("ALT: "))

    # Transform y=100, terrain y=20, half-height=4 => clearance is 76.
    assert alt_line == "ALT: 76.0 m"


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
        return [0, 1], ["spawn_above_target"]

    def _fake_run_once_record(config, *, seed, scenario):
        _ = config, scenario
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
        level_name="level_eval",
        bot_name="turtle",
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
        eval_scenario=None,
        batch_seeds="0-1",
        batch_scenarios="spawn_above_target",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )
    exit_code = _run_batch(config)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Batch workers unavailable (RuntimeError" in out


def test_run_batch_rejects_empty_seed_plan(monkeypatch) -> None:
    def _fake_plan(_config):
        return [], ["spawn_above_target"]

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)

    config = RunConfig(
        level_name="level_eval",
        bot_name="turtle",
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
        eval_scenario=None,
        batch_seeds="",
        batch_scenarios="spawn_above_target",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )

    with pytest.raises(ValueError, match="resolved no seeds"):
        _run_batch(config)


def test_run_batch_rejects_empty_scenario_plan(monkeypatch) -> None:
    def _fake_plan(_config):
        return [0, 1], []

    monkeypatch.setattr(main_module, "_resolve_batch_plan", _fake_plan)

    config = RunConfig(
        level_name="level_eval",
        bot_name="turtle",
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
        eval_scenario=None,
        batch_seeds="0-1",
        batch_scenarios="",
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=2,
    )

    with pytest.raises(ValueError, match="resolved no scenarios"):
        _run_batch(config)
