from __future__ import annotations

from types import SimpleNamespace

from game.core.bot import Bot, BotAction, Sensors
from game.core.components import (
    ActorControlRole,
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    PhysicsState,
    PlayerControlled,
    PlayerSelectable,
    Radar,
    RefuelConfig,
    Transform,
)
from game.core.ecs import Entity, World
from game.core.maths import Vector2
from bot_framework.bot_actor_session import active_actor_bot, attach_primary_bot
from game.runtime.actor_policy import find_initial_player_actor_uid
from game.runtime.actor_registry import find_first_actor_for_role
from game.runtime.player_session import set_active_actor, switch_active_actor
from game.runtime.sensors import build_vehicle_info
from game.runtime.terrain_intel import build_bot_environment


class _FakeEngine:
    def __init__(self) -> None:
        self.primary_actor_uid: str | None = None

    def set_primary_actor(self, uid: str | None) -> None:
        self.primary_actor_uid = uid


class _Bot(Bot):
    def update(self, dt: float, sensors: Sensors) -> BotAction:
        _ = dt, sensors
        return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)


def _make_actor(
    uid: str,
    *,
    selectable_order: int | None = None,
    active: bool = False,
    role: str = "none",
) -> Entity:
    actor = Entity(uid=uid)
    actor.add_component(Transform())
    actor.add_component(PhysicsState())
    actor.add_component(FuelTank())
    actor.add_component(Engine())
    actor.add_component(LanderGeometry())
    actor.add_component(LanderState())
    actor.add_component(Radar())
    actor.add_component(RefuelConfig())
    actor.add_component(ActorControlRole(role=role))
    if selectable_order is not None:
        actor.add_component(PlayerSelectable(order=selectable_order))
    if active:
        actor.add_component(PlayerControlled(active=True))
    return actor


def _make_level() -> SimpleNamespace:
    class _Terrain:
        def __call__(self, x: float, lod: int = 0) -> float:
            _ = x, lod
            return 0.0

    class _Sites:
        def get_sites(self, _range: object) -> list[SimpleNamespace]:
            return [SimpleNamespace(uid="target", x=120.0, y=0.0, size=110.0)]

    runtime_context = SimpleNamespace(
        level_name="demo",
        public_scenario_name="demo:mid:half",
        scenario_name="demo:mid:half",
        eval_target_pos=None,
    )
    return SimpleNamespace(
        terrain=_Terrain(),
        sites=_Sites(),
        _scenario_params={"hazard_driver": "demo_driver", "obstacle_support_x0": 88.0},
        ensure_runtime_context=lambda: runtime_context,
    )


def _make_backstop_level() -> SimpleNamespace:
    class _Terrain:
        def __call__(self, x: float, lod: int = 0) -> float:
            _ = lod
            x = float(x)
            if x < 160.0:
                return 0.0
            if x < 180.0:
                return (x - 160.0) * 13.0
            return 260.0

        def get_resolution(self, lod: int = 0) -> float:
            _ = lod
            return 2.0

    class _Sites:
        def get_sites(self, _range: object) -> list[SimpleNamespace]:
            return [SimpleNamespace(uid="target", x=120.0, y=0.0, size=110.0)]

    runtime_context = SimpleNamespace(
        level_name="terrain",
        public_scenario_name="terrain:reactive:terminal_backstop",
        scenario_name="terrain:reactive:terminal_backstop",
        eval_target_pos=None,
    )
    return SimpleNamespace(
        terrain=_Terrain(),
        sites=_Sites(),
        _scenario_params={"hazard_driver": "containment_backstop"},
        ensure_runtime_context=lambda: runtime_context,
    )


def test_find_initial_player_actor_uid_prefers_explicit_active() -> None:
    actors = [
        _make_actor("a", selectable_order=2),
        _make_actor("b", selectable_order=0, active=True),
        _make_actor("c", selectable_order=1),
    ]
    assert find_initial_player_actor_uid(actors) == "b"


def test_find_initial_player_actor_uid_falls_back_to_lowest_selectable_order() -> None:
    actors = [
        _make_actor("a", selectable_order=2),
        _make_actor("b", selectable_order=0),
        _make_actor("c", selectable_order=1),
    ]
    assert find_initial_player_actor_uid(actors) == "b"


def test_set_active_actor_updates_world_and_engine_sync() -> None:
    actors = [
        _make_actor("a", selectable_order=0, active=True),
        _make_actor("b", selectable_order=1),
    ]
    ecs_world = World()
    for actor in actors:
        ecs_world.add_entity(actor)
    level = SimpleNamespace(world=SimpleNamespace(primary_actor_uid=None, lander=None))
    engine = _FakeEngine()

    active = set_active_actor(
        actors=actors,
        ecs_world=ecs_world,
        level=level,
        engine=engine,
        uid="b",
    )

    assert active is not None
    assert active.uid == "b"
    assert actors[0].get_component(PlayerControlled).active is False
    assert actors[1].get_component(PlayerControlled).active is True
    assert level.world.primary_actor_uid == "b"
    assert level.world.lander is active
    assert engine.primary_actor_uid == "b"


def test_switch_active_actor_wraps_by_selectable_order() -> None:
    actors = [
        _make_actor("a", selectable_order=10),
        _make_actor("b", selectable_order=0),
        _make_actor("c", selectable_order=5),
    ]
    ecs_world = World()
    for actor in actors:
        ecs_world.add_entity(actor)
    level = SimpleNamespace(world=SimpleNamespace(primary_actor_uid=None, lander=None))
    engine = _FakeEngine()

    switched = switch_active_actor(
        actors=actors,
        ecs_world=ecs_world,
        level=level,
        engine=engine,
        active_uid="c",
        delta=1,
    )

    assert switched is not None
    next_uid, active_actor = switched
    assert next_uid == "a"
    assert active_actor.uid == "a"


def test_attach_primary_bot_prefers_actor_with_bot_role() -> None:
    actors = [
        _make_actor("player", selectable_order=0, active=True, role="human"),
        _make_actor("wingman", selectable_order=1, role="bot"),
    ]
    ecs_world = World()
    for actor in actors:
        ecs_world.add_entity(actor)
    bot = _Bot()
    actor_bots: dict[str, Bot] = {}

    attach_primary_bot(
        actors=actors,
        actor_bots=actor_bots,
        ecs_world=ecs_world,
        level=_make_level(),
        active_uid="player",
        bot=bot,
        find_first_actor_for_role=find_first_actor_for_role,
        build_vehicle_info=build_vehicle_info,
        build_bot_environment=build_bot_environment,
    )

    assert actor_bots == {"wingman": bot}
    assert bot.vehicle_info is not None
    assert bot.environment is not None
    assert bot.environment.target is not None
    assert bot.environment.target.uid == "target"
    assert bot.environment.terrain_summary is not None
    assert bot.environment.terrain_summary.left_boundary is None
    assert bot.environment.terrain_summary.right_boundary is None
    assert bot.environment.scenario_params == {
        "hazard_driver": "demo_driver",
        "obstacle_support_x0": 88.0,
    }
    assert (
        active_actor_bot(
            actor_bots=actor_bots,
            active_uid="wingman",
            primary_bot=None,
        )
        is bot
    )


def test_attach_primary_bot_falls_back_to_non_active_actor() -> None:
    actors = [
        _make_actor("player", selectable_order=0, active=True),
        _make_actor("escort", selectable_order=1),
    ]
    ecs_world = World()
    for actor in actors:
        ecs_world.add_entity(actor)
    bot = _Bot()
    actor_bots: dict[str, Bot] = {}

    attach_primary_bot(
        actors=actors,
        actor_bots=actor_bots,
        ecs_world=ecs_world,
        level=_make_level(),
        active_uid="player",
        bot=bot,
        find_first_actor_for_role=find_first_actor_for_role,
        build_vehicle_info=build_vehicle_info,
        build_bot_environment=build_bot_environment,
    )

    assert actor_bots == {"escort": bot}


def test_build_bot_environment_precomputes_target_side_terrain_boundaries() -> None:
    actor = _make_actor("bot")
    actor.get_component(Transform).pos.x = 0.0
    actor.start_pos = Vector2(0.0, 0.0)

    environment = build_bot_environment(level=_make_backstop_level(), actor=actor)

    assert environment is not None
    assert environment.target is not None
    assert environment.terrain_summary is not None
    assert environment.terrain_summary.target_ground_y == 0.0
    assert environment.terrain_summary.left_boundary is None
    assert environment.terrain_summary.right_boundary is not None
    assert environment.terrain_summary.right_boundary.direction == 1
    assert environment.terrain_summary.right_boundary.x == 164.0
    assert environment.terrain_summary.right_boundary.steepness > 5.0
    assert environment.terrain_summary.right_boundary.tail_steepness == 0.0
