from __future__ import annotations

from core.components import Transform
from core.ecs import Entity, World
from core.maths import Vector2
from runtime.plot_events import track_plot_events


class _Bot:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot

    def get_evaluation_snapshot(self):
        return self._snapshot


class _Plotter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def mark_event(self, *, name: str, x: float, y: float, label: str) -> None:
        _ = x, y
        self.events.append((name, label))


def test_track_plot_events_marks_setup_and_flare_once() -> None:
    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(10.0, 20.0)))
    world = World()
    world.add_entity(actor)
    plotter = _Plotter()
    seen: set[tuple[str, str]] = set()

    track_plot_events(
        actor_bots={
            "lander": _Bot(
                {
                    "kind": "zem_zev",
                    "setup_gate_done": True,
                    "setup_gate_projected_dx": 12.34,
                    "setup_gate_projected_apex_over_target": 56.78,
                    "terminal_gate_done": True,
                    "terminal_gate_projected_dx": -4.56,
                }
            )
        },
        ecs_world=world,
        plotter=plotter,
        events_seen=seen,
    )
    track_plot_events(
        actor_bots={
            "lander": _Bot(
                {
                    "kind": "zem_zev",
                    "setup_gate_done": True,
                    "setup_gate_projected_dx": 12.34,
                    "setup_gate_projected_apex_over_target": 56.78,
                    "terminal_gate_done": True,
                    "terminal_gate_projected_dx": -4.56,
                }
            )
        },
        ecs_world=world,
        plotter=plotter,
        events_seen=seen,
    )

    assert plotter.events == [
        ("setup_gate", "setup gate pdx=12.3 pax=56.8"),
        ("flare_gate", "flare gate pdx=-4.6"),
    ]


def test_track_plot_events_ignores_non_zem_snapshots_and_missing_actor() -> None:
    plotter = _Plotter()

    track_plot_events(
        actor_bots={"lander": _Bot({"kind": "other", "setup_gate_done": True})},
        ecs_world=World(),
        plotter=plotter,
        events_seen=set(),
    )

    assert plotter.events == []
