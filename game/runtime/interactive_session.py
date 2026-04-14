from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from game.core.components import (
    ControlIntent,
    Engine,
    FlightState,
    FuelTank,
    LanderState,
    PhysicsState,
    Transform,
)
from game.core.ecs import require_component
from game.core.maths import Vector2

if TYPE_CHECKING:
    from game.core.physics import PhysicsEngine


def reset_lander_entity(entity: Any) -> None:
    trans = require_component(entity, Transform)
    phys = require_component(entity, PhysicsState)
    tank = require_component(entity, FuelTank)
    eng = require_component(entity, Engine)
    ls = require_component(entity, LanderState)
    intent = require_component(entity, ControlIntent)
    start_pos = getattr(entity, "start_pos", Vector2(0.0, 0.0))
    trans.pos = Vector2(start_pos)
    trans.rotation = 0.0
    phys.vel.update(0.0, 0.0)
    phys.acc.update(0.0, 0.0)
    tank.fuel = tank.max_fuel
    eng.thrust_level = 0.0
    eng.target_thrust = 0.0
    eng.target_angle = 0.0
    ls.state = FlightState.FLYING
    intent.target_thrust = None
    intent.target_angle = None
    intent.refuel_requested = False


def reset_active_actor_session(
    *,
    active_actor: Any,
    engine: PhysicsEngine,
    renderer: Any,
    bot_override_delay: float,
) -> float:
    reset_lander_entity(active_actor)
    trans = require_component(active_actor, Transform)
    engine.unfreeze(uid=active_actor.uid)
    engine.teleport(
        trans.pos,
        angle=trans.rotation,
        clear_velocity=True,
        uid=active_actor.uid,
    )
    if renderer is not None:
        cam = renderer.main_camera
        cam.x = trans.pos.x
        cam.y = trans.pos.y
        cam.zoom = 2.0
    return float(bot_override_delay)


@dataclass(frozen=True)
class InputStepResult:
    user_controls: tuple[float, float, bool] | None
    input_events: dict[str, Any]
    running: bool


def process_interactive_input(
    *,
    headless: bool,
    input_handler: Any,
    renderer: Any,
    player_controller: Any,
    frame_dt: float,
    get_active_actor: Callable[[], Any],
    on_reset: Callable[[], None],
    on_switch_actor: Callable[[], None],
) -> InputStepResult:
    if headless or input_handler is None:
        return InputStepResult(user_controls=None, input_events={}, running=True)

    input_events = input_handler.get_events()
    if input_events.get("quit"):
        return InputStepResult(
            user_controls=None, input_events=input_events, running=False
        )

    if input_events.get("reset"):
        on_reset()
        input_events = {**input_events, "reset": False}
    if input_events.get("switch_actor"):
        on_switch_actor()
        input_events = {**input_events, "switch_actor": False}

    user_controls = None
    active_actor = get_active_actor()
    ls = require_component(active_actor, LanderState)
    eng = require_component(active_actor, Engine)
    if ls.state in ("flying", "landed") and player_controller is not None:
        user_controls = player_controller.update(
            input_events,
            frame_dt,
            eng.target_thrust,
            eng.max_thrust,
            eng.target_angle,
            eng.max_rotation_rate,
        )

    if renderer is not None:
        cam = renderer.main_camera
        if hasattr(cam, "handle_input"):
            cam.handle_input(input_events, frame_dt)
        if input_events.get("toggle_ballistic"):
            toggle_ballistic = getattr(renderer, "toggle_ballistic_overlay", None)
            if callable(toggle_ballistic):
                toggle_ballistic()

    return InputStepResult(
        user_controls=user_controls, input_events=input_events, running=True
    )


def render_frame(
    *,
    headless: bool,
    renderer: Any,
    active_bot: Any,
    frame_dt: float,
    target_fps: float,
) -> float:
    if not headless and renderer is not None:
        renderer.update(frame_dt)
        renderer.draw(bot=active_bot)
        return float(renderer.tick(target_fps))
    return 1.0 / float(target_fps)
