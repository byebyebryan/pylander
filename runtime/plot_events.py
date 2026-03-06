from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.bot import FlightPhaseSnapshot, PlotMarker
from core.components import Transform

_SHARED_MILESTONE_LABELS: dict[str, tuple[str, str]] = {
    "setup_gate": ("setup_gate", "setup gate"),
}


def _safe_phase_snapshot(bot: Any) -> FlightPhaseSnapshot | None:
    getter = getattr(bot, "get_flight_phase_snapshot", None)
    if not callable(getter):
        return None
    try:
        snapshot = getter()
    except Exception:
        return None
    if not isinstance(snapshot, FlightPhaseSnapshot):
        return None
    return snapshot


def _safe_plot_markers(bot: Any) -> tuple[PlotMarker, ...]:
    getter = getattr(bot, "get_plot_markers", None)
    if not callable(getter):
        return ()
    try:
        markers = getter()
    except Exception:
        return ()
    if not isinstance(markers, Iterable):
        return ()
    out: list[PlotMarker] = []
    for marker in markers:
        if isinstance(marker, PlotMarker):
            out.append(marker)
    return tuple(out)


def _emit_plot_event(
    *,
    plotter: Any,
    events_seen: set[tuple[str, str]],
    actor_uid: str,
    event_id: str,
    event_name: str,
    label: str | None,
    default_x: float,
    default_y: float,
    x: float | None = None,
    y: float | None = None,
    metadata: dict[str, float | str | None] | None = None,
) -> None:
    event_key = (actor_uid, event_id)
    if event_key in events_seen:
        return
    try:
        event_x = default_x if x is None else float(x)
    except (TypeError, ValueError):
        event_x = default_x
    try:
        event_y = default_y if y is None else float(y)
    except (TypeError, ValueError):
        event_y = default_y
    plotter.mark_event(
        name=event_name,
        x=event_x,
        y=event_y,
        label=label,
        metadata=metadata,
    )
    events_seen.add(event_key)


def track_plot_events(
    *,
    actor_bots: dict[str, Any],
    ecs_world: Any,
    plotter: Any,
    events_seen: set[tuple[str, str]],
) -> None:
    for uid, bot in actor_bots.items():
        actor = ecs_world.get_entity_by_id(uid)
        if actor is None:
            continue
        trans = actor.get_component(Transform)
        if trans is None:
            continue
        default_x = float(trans.pos.x)
        default_y = float(trans.pos.y)

        for marker in _safe_plot_markers(bot):
            event_id = str(marker.id).strip()
            event_name = str(marker.name).strip()
            if not event_id or not event_name:
                continue
            label = None if marker.label is None else str(marker.label)
            _emit_plot_event(
                plotter=plotter,
                events_seen=events_seen,
                actor_uid=uid,
                event_id=event_id,
                event_name=event_name,
                label=label,
                default_x=default_x,
                default_y=default_y,
                x=marker.x,
                y=marker.y,
                metadata=dict(marker.metadata),
            )

        phase_snapshot = _safe_phase_snapshot(bot)
        if phase_snapshot is not None:
            for milestone in phase_snapshot.milestones:
                marker_spec = _SHARED_MILESTONE_LABELS.get(str(milestone))
                if marker_spec is None:
                    continue
                event_name, label = marker_spec
                _emit_plot_event(
                    plotter=plotter,
                    events_seen=events_seen,
                    actor_uid=uid,
                    event_id=str(milestone),
                    event_name=event_name,
                    label=label,
                    default_x=default_x,
                    default_y=default_y,
                )
