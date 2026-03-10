from __future__ import annotations

from core.bot import FlightPhaseSnapshot, PlotMarker
from core.components import Transform
from core.ecs import Entity, World
from core.maths import Vector2
from runtime.plot_events import track_plot_events


class _Bot:
    def __init__(
        self,
        *,
        phase_snapshot: FlightPhaseSnapshot | None = None,
        plot_markers: tuple[PlotMarker, ...] = (),
    ) -> None:
        self._phase_snapshot = phase_snapshot
        self._plot_markers = plot_markers

    def get_flight_phase_snapshot(self) -> FlightPhaseSnapshot | None:
        return self._phase_snapshot

    def get_plot_markers(self) -> tuple[PlotMarker, ...]:
        return self._plot_markers


class _Plotter:
    def __init__(self) -> None:
        self.events: list[tuple[str, float, float, str, dict[str, float | str | None] | None]] = []

    def mark_event(
        self,
        *,
        name: str,
        x: float,
        y: float,
        label: str,
        metadata: dict[str, float | str | None] | None = None,
    ) -> None:
        self.events.append((name, x, y, label, metadata))


def test_track_plot_events_marks_setup_and_flare_entry_once() -> None:
    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(10.0, 20.0)))
    world = World()
    world.add_entity(actor)
    plotter = _Plotter()
    seen: set[tuple[str, str]] = set()

    track_plot_events(
        actor_bots={
            "lander": _Bot(
                phase_snapshot=FlightPhaseSnapshot(phase="coast", milestones=("setup_gate",)),
                plot_markers=(
                    PlotMarker(
                        id="setup_gate",
                        name="setup_gate",
                        label="setup gate",
                        x=14.0,
                        y=26.0,
                        metadata={"vx": 3.5, "vy_up": -7.0},
                    ),
                    PlotMarker(
                        id="flare_entry",
                        name="flare_entry",
                        label="flare entry pdx=-4.6",
                    ),
                ),
            )
        },
        ecs_world=world,
        plotter=plotter,
        events_seen=seen,
    )
    track_plot_events(
        actor_bots={
            "lander": _Bot(
                phase_snapshot=FlightPhaseSnapshot(phase="coast", milestones=("setup_gate",)),
                plot_markers=(
                    PlotMarker(
                        id="setup_gate",
                        name="setup_gate",
                        label="setup gate",
                        x=14.0,
                        y=26.0,
                        metadata={"vx": 3.5, "vy_up": -7.0},
                    ),
                    PlotMarker(
                        id="flare_entry",
                        name="flare_entry",
                        label="flare entry pdx=-4.6",
                    ),
                ),
            )
        },
        ecs_world=world,
        plotter=plotter,
        events_seen=seen,
    )

    assert plotter.events == [
        ("setup_gate", 14.0, 26.0, "setup gate", {"vx": 3.5, "vy_up": -7.0}),
        ("flare_entry", 10.0, 20.0, "flare entry pdx=-4.6", {}),
    ]


def test_track_plot_events_uses_marker_coordinates_when_provided() -> None:
    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(10.0, 20.0)))
    world = World()
    world.add_entity(actor)
    plotter = _Plotter()

    track_plot_events(
        actor_bots={
            "lander": _Bot(
                plot_markers=(
                    PlotMarker(
                        id="custom",
                        name="flare_entry",
                        label="custom marker",
                        x=42.0,
                        y=84.0,
                    ),
                ),
            )
        },
        ecs_world=world,
        plotter=plotter,
        events_seen=set(),
    )

    assert plotter.events == [("flare_entry", 42.0, 84.0, "custom marker", {})]


def test_track_plot_events_ignores_missing_actor_and_empty_markers() -> None:
    plotter = _Plotter()

    track_plot_events(
        actor_bots={"lander": _Bot()},
        ecs_world=World(),
        plotter=plotter,
        events_seen=set(),
    )

    assert plotter.events == []
