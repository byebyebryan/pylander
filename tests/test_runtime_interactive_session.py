from __future__ import annotations

from core.components import ControlIntent, Engine, FuelTank, LanderState, PhysicsState, Transform
from core.ecs import Entity
from core.maths import Vector2
from runtime.interactive_session import (
    process_interactive_input,
    render_frame,
    reset_active_actor_session,
)


class _InputHandler:
    def __init__(self, events):
        self._events = events

    def get_events(self):
        return dict(self._events)


class _PlayerController:
    def __init__(self, controls):
        self._controls = controls
        self.calls = 0

    def update(self, *args):
        self.calls += 1
        return self._controls


class _Camera:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, float]] = []
        self.x = 99.0
        self.y = 77.0
        self.zoom = 5.0

    def handle_input(self, events, dt: float) -> None:
        self.calls.append((dict(events), dt))


class _Renderer:
    def __init__(self) -> None:
        self.main_camera = _Camera()
        self.ballistic_toggles = 0
        self.bot = None
        self.updated = 0
        self.drawn = 0
        self.tick_fps = None

    def toggle_ballistic_overlay(self) -> None:
        self.ballistic_toggles += 1

    def update(self, _dt: float) -> None:
        self.updated += 1

    def draw(self) -> None:
        self.drawn += 1

    def tick(self, fps: float) -> float:
        self.tick_fps = fps
        return 0.25


class _EngineAdapter:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def teleport_lander(self, _pos, *, angle: float, clear_velocity: bool, uid: str) -> None:
        _ = angle, clear_velocity
        self.calls.append(uid)


def _make_actor() -> Entity:
    actor = Entity("lander")
    actor.start_pos = Vector2(10.0, 20.0)
    actor.add_component(Transform(pos=Vector2(50.0, 60.0), rotation=1.5))
    actor.add_component(PhysicsState(vel=Vector2(3.0, 4.0), acc=Vector2(5.0, 6.0)))
    actor.add_component(FuelTank(fuel=12.0, max_fuel=100.0))
    actor.add_component(Engine(thrust_level=1.0, target_thrust=0.7, target_angle=0.4))
    actor.add_component(LanderState(state="landed"))
    actor.add_component(ControlIntent(target_thrust=0.1, target_angle=0.2, refuel_requested=True))
    return actor


def test_process_interactive_input_handles_quit_reset_switch_and_camera() -> None:
    actor = _make_actor()
    renderer = _Renderer()
    controller = _PlayerController((0.6, -0.1, False))
    calls: list[str] = []

    result = process_interactive_input(
        headless=False,
        input_handler=_InputHandler(
            {"reset": True, "switch_actor": True, "toggle_ballistic": True}
        ),
        renderer=renderer,
        player_controller=controller,
        frame_dt=0.1,
        get_active_actor=lambda: actor,
        on_reset=lambda: calls.append("reset"),
        on_switch_actor=lambda: calls.append("switch"),
    )

    assert result.running is True
    assert result.user_controls == (0.6, -0.1, False)
    assert result.input_events["reset"] is False
    assert result.input_events["switch_actor"] is False
    assert calls == ["reset", "switch"]
    assert renderer.ballistic_toggles == 1
    assert renderer.main_camera.calls == [({"reset": False, "switch_actor": False, "toggle_ballistic": True}, 0.1)]
    assert controller.calls == 1


def test_process_interactive_input_quit_stops_run() -> None:
    result = process_interactive_input(
        headless=False,
        input_handler=_InputHandler({"quit": True}),
        renderer=None,
        player_controller=None,
        frame_dt=0.1,
        get_active_actor=lambda: _make_actor(),
        on_reset=lambda: None,
        on_switch_actor=lambda: None,
    )

    assert result.running is False
    assert result.user_controls is None


def test_reset_active_actor_session_resets_entity_and_camera() -> None:
    actor = _make_actor()
    renderer = _Renderer()
    engine_adapter = _EngineAdapter()

    override_timer = reset_active_actor_session(
        active_actor=actor,
        engine_adapter=engine_adapter,
        renderer=renderer,
        bot_override_delay=1.0,
    )

    trans = actor.get_component(Transform)
    phys = actor.get_component(PhysicsState)
    tank = actor.get_component(FuelTank)
    eng = actor.get_component(Engine)
    ls = actor.get_component(LanderState)
    intent = actor.get_component(ControlIntent)

    assert override_timer == 1.0
    assert trans is not None and (trans.pos.x, trans.pos.y, trans.rotation) == (10.0, 20.0, 0.0)
    assert phys is not None and (phys.vel.x, phys.vel.y, phys.acc.x, phys.acc.y) == (0.0, 0.0, 0.0, 0.0)
    assert tank is not None and tank.fuel == tank.max_fuel
    assert eng is not None and (eng.thrust_level, eng.target_thrust, eng.target_angle) == (0.0, 0.0, 0.0)
    assert ls is not None and ls.state == "flying"
    assert intent is not None and intent.target_thrust is None and intent.target_angle is None and intent.refuel_requested is False
    assert engine_adapter.calls == ["lander"]
    assert (renderer.main_camera.x, renderer.main_camera.y, renderer.main_camera.zoom) == (10.0, 20.0, 2.0)


def test_render_frame_updates_renderer_or_returns_fixed_headless_dt() -> None:
    renderer = _Renderer()

    dt = render_frame(
        headless=False,
        renderer=renderer,
        active_bot="bot",
        frame_dt=0.1,
        target_fps=60.0,
    )
    headless_dt = render_frame(
        headless=True,
        renderer=renderer,
        active_bot="ignored",
        frame_dt=0.1,
        target_fps=60.0,
    )

    assert dt == 0.25
    assert renderer.bot == "bot"
    assert renderer.updated == 1
    assert renderer.drawn == 1
    assert renderer.tick_fps == 60.0
    assert headless_dt == 1.0 / 60.0
