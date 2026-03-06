from __future__ import annotations

import pytest

from bots import create_bot
from bots._ballistics import (
    BallisticProjection,
    ballistic_time_to_impact,
    ballistic_time_to_impact_from_result,
    estimate_ballistic_projection,
    estimate_ballistic_projection_from_result,
)
from core.bot import BotAction, PassiveSensors, QueryBot
from core.bot_queries import (
    BallisticResult,
    BotQueryBallistic,
    BotQueryRaycast,
    BotQueryTerrainProfile,
    RaycastResult,
    TerrainProfileResult,
)
from core.components import PhysicsState, Transform
from core.ecs import require_component
from game import LanderGame
from levels import create_level as create_level_by_name
import runtime.bot_query_eval as bot_query_eval_module
from runtime.bot_query_eval import evaluate_bot_queries


def _build_game(level_name: str = "flare", bot_name: str = "zem_zev") -> LanderGame:
    level = create_level_by_name(level_name)
    return LanderGame(level=level, seed=0, bot=create_bot(bot_name), headless=True)


def test_evaluate_bot_queries_returns_expected_payload_types() -> None:
    game = _build_game()
    actor = game.level.world.actors[0]
    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)

    queries = [
        BotQueryRaycast(id="ray", dir_angle=0.0, max_range=600.0),
        BotQueryTerrainProfile(
            id="profile",
            x_start=float(trans.pos.x) - 100.0,
            x_end=float(trans.pos.x) + 100.0,
            samples=7,
            lod=0,
        ),
        BotQueryBallistic(
            id="ballistic",
            x=float(trans.pos.x),
            y=float(trans.pos.y),
            vx=float(phys.vel.x),
            vy_up=float(phys.vel.y),
            max_distance=1200.0,
            max_points=64,
            segment_length=20.0,
            lod=0,
            clearance=0.0,
        ),
    ]

    results, stats = evaluate_bot_queries(actor, game.engine_adapter, game.terrain, queries)

    assert stats.total == 3
    assert stats.raycast == 1
    assert stats.terrain_profile == 1
    assert stats.ballistic == 1

    assert isinstance(results["ray"], RaycastResult)
    assert isinstance(results["profile"], TerrainProfileResult)
    assert isinstance(results["ballistic"], BallisticResult)
    assert len(results["profile"].points) == 7
    assert len(results["ballistic"].points) >= 1


def test_evaluate_bot_queries_ballistic_dedupes_identical_requests(monkeypatch) -> None:
    game = _build_game()
    actor = game.level.world.actors[0]
    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)

    original = bot_query_eval_module.sample_ballistic_trajectory
    call_counter = {"count": 0}

    def _wrapped(*args, **kwargs):
        call_counter["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(bot_query_eval_module, "sample_ballistic_trajectory", _wrapped)

    q1 = BotQueryBallistic(
        id="b1",
        x=float(trans.pos.x),
        y=float(trans.pos.y),
        vx=float(phys.vel.x),
        vy_up=float(phys.vel.y),
        max_distance=1200.0,
        max_points=64,
        segment_length=20.0,
        lod=0,
        clearance=0.0,
    )
    q2 = BotQueryBallistic(
        id="b2",
        x=float(trans.pos.x),
        y=float(trans.pos.y),
        vx=float(phys.vel.x),
        vy_up=float(phys.vel.y),
        max_distance=1200.0,
        max_points=64,
        segment_length=20.0,
        lod=0,
        clearance=0.0,
    )
    results, stats = evaluate_bot_queries(actor, game.engine_adapter, game.terrain, [q1, q2])

    assert stats.total == 2
    assert stats.ballistic == 2
    assert call_counter["count"] == 1
    assert results["b1"] is not results["b2"]
    assert results["b1"].points == results["b2"].points


def test_evaluate_bot_queries_rejects_duplicate_ids() -> None:
    game = _build_game()
    actor = game.level.world.actors[0]

    with pytest.raises(ValueError, match="Duplicate bot query id"):
        evaluate_bot_queries(
            actor,
            game.engine_adapter,
            game.terrain,
            [
                BotQueryRaycast(id="dup", dir_angle=0.0),
                BotQueryTerrainProfile(id="dup", x_start=-10.0, x_end=10.0),
            ],
        )


def test_query_bot_path_and_profile_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CountingQueryBot(QueryBot):
        def __init__(self) -> None:
            super().__init__()
            self.plan_calls = 0
            self.act_calls = 0

        def plan(self, dt: float, passive: PassiveSensors):
            _ = dt, passive
            self.plan_calls += 1
            return []

        def act(self, dt: float, passive: PassiveSensors, results):
            _ = dt, passive, results
            self.act_calls += 1
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    monkeypatch.setenv("PYLANDER_BOT_PROFILE", "1")
    monkeypatch.setenv("PYLANDER_BOT_PROFILE_INTERVAL_S", "0.25")
    level = create_level_by_name("flat")
    bot = _CountingQueryBot()
    game = LanderGame(level=level, seed=0, bot=bot, headless=True)
    result = game.run(print_freq=0, max_steps=30, max_time=10.0)

    assert bot.plan_calls > 0
    assert bot.act_calls == bot.plan_calls
    assert result["bot_profile_enabled"] is True
    assert result["bot_profile_ticks"] > 0
    assert result["bot_profile_query_total"] == 0


def test_query_demo_bot_runs_headless_with_query_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLANDER_BOT_PROFILE", "1")
    level = create_level_by_name("flare")
    game = LanderGame(level=level, seed=0, bot=create_bot("query_demo"), headless=True)
    result = game.run(print_freq=0, max_steps=40, max_time=10.0)

    assert result["bot_profile_enabled"] is True
    assert result["bot_profile_ticks"] > 0
    assert result["bot_profile_query_total"] > 0


def test_ballistic_projection_decoder_matches_legacy_for_sensor_hit() -> None:
    passive = PassiveSensors(
        x=10.0,
        y=200.0,
        altitude=200.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=15.0,
        vy_up=-30.0,
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
    fake_result = BallisticResult(
        points=[(10.0, 200.0), (20.0, 160.0)],
        hit=True,
        hit_x=60.0,
        hit_y=0.0,
        hit_time=2.8,
        hit_vx=15.0,
        hit_vy_up=-45.0,
        hit_speed=47.0,
        distance=180.0,
        duration=2.8,
        termination="terrain",
    )

    decoded = estimate_ballistic_projection_from_result(
        dx=20.0,
        alt=passive.altitude,
        vx=passive.vx,
        vy_up=passive.vy_up,
        x=passive.x,
        result=fake_result,
    )
    assert isinstance(decoded, BallisticProjection)
    assert decoded.used_sensor is True
    assert decoded.target_x == pytest.approx(30.0)
    assert decoded.projected_dx == pytest.approx(-30.0)
    assert decoded.t_fall == pytest.approx(2.8)


def test_ballistic_time_to_impact_decoder_falls_back_without_hit() -> None:
    passive = PassiveSensors(
        x=0.0,
        y=150.0,
        altitude=150.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=-10.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=1000.0,
        thrust_level=0.0,
        fuel=100.0,
        max_fuel=100.0,
        state="flying",
        radar_contacts=[],
        proximity=None,
    )
    t_result, src = ballistic_time_to_impact_from_result(
        passive,
        BallisticResult(
            points=[(0.0, 150.0)],
            hit=False,
            hit_x=None,
            hit_y=None,
            hit_time=None,
            hit_vx=None,
            hit_vy_up=None,
            hit_speed=None,
            distance=0.0,
            duration=0.0,
            termination="max_distance",
        ),
    )
    t_legacy, src_legacy = ballistic_time_to_impact(passive, active=None)
    assert src == "analytic"
    assert src_legacy == "analytic"
    assert t_result == pytest.approx(t_legacy)


def test_projection_decoder_falls_back_without_result_like_legacy() -> None:
    projection = estimate_ballistic_projection_from_result(
        dx=80.0,
        alt=120.0,
        vx=10.0,
        vy_up=-15.0,
        x=25.0,
        result=None,
    )
    legacy = estimate_ballistic_projection(
        dx=80.0,
        alt=120.0,
        vx=10.0,
        vy_up=-15.0,
        x=25.0,
        y=120.0,
        active=None,
        clearance=0.0,
    )
    assert projection.projected_dx == pytest.approx(legacy.projected_dx)
    assert projection.t_fall == pytest.approx(legacy.t_fall)
    assert projection.used_sensor is False


def test_plunge_uses_query_path_but_zem_is_queryless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLANDER_BOT_PROFILE", "1")

    plunge = create_bot("plunge")
    assert isinstance(plunge, QueryBot)
    plunge_game = LanderGame(
        level=create_level_by_name("plunge"),
        seed=0,
        bot=plunge,
        headless=True,
    )
    plunge_result = plunge_game.run(print_freq=0, max_steps=40, max_time=20.0)
    assert plunge_result["bot_profile_query_total"] > 0

    zem = create_bot("zem_zev")
    assert isinstance(zem, QueryBot)
    zem_game = LanderGame(
        level=create_level_by_name("flare"),
        seed=0,
        bot=zem,
        headless=True,
    )
    zem_result = zem_game.run(print_freq=0, max_steps=40, max_time=20.0)
    assert zem_result["bot_profile_query_total"] == 0
