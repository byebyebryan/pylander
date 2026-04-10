from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from game.core.bot import BoostCutoffMetrics, PlotMarker
from game.core.components import Transform
from .result_pipeline import _safe_phase_snapshot

_SHARED_MILESTONE_LABELS: dict[str, tuple[str, str]] = {
    "boost_cutoff": ("boost_cutoff", "boost cutoff"),
}


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


def _boost_cutoff_event_payload(
    boost_cutoff: BoostCutoffMetrics | None,
) -> tuple[float | None, float | None, dict[str, float | str | None] | None]:
    if boost_cutoff is None:
        return None, None, None
    metadata: dict[str, float | str | None] = {}
    for key in ("time_s", "vx", "vy_up"):
        value = getattr(boost_cutoff, key, None)
        if value is None:
            continue
        metadata[key] = float(value)
    x = getattr(boost_cutoff, "x", None)
    y = getattr(boost_cutoff, "y", None)
    event_x = None if x is None else float(x)
    event_y = None if y is None else float(y)
    if event_x is None and event_y is None and not metadata:
        return None, None, None
    return event_x, event_y, metadata


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

        phase_snapshot = _safe_phase_snapshot(bot)
        if phase_snapshot is not None:
            for milestone in phase_snapshot.milestones:
                marker_spec = _SHARED_MILESTONE_LABELS.get(str(milestone))
                if marker_spec is None:
                    continue
                event_name, label = marker_spec
                event_x = None
                event_y = None
                metadata: dict[str, float | str | None] | None = None
                if event_name == "boost_cutoff":
                    event_x, event_y, metadata = _boost_cutoff_event_payload(
                        phase_snapshot.boost_cutoff
                    )
                    if event_x is None and event_y is None and metadata is None:
                        continue
                _emit_plot_event(
                    plotter=plotter,
                    events_seen=events_seen,
                    actor_uid=uid,
                    event_id=str(milestone),
                    event_name=event_name,
                    label=label,
                    default_x=default_x,
                    default_y=default_y,
                    x=event_x,
                    y=event_y,
                    metadata=metadata,
                )

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
