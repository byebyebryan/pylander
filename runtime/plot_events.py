from __future__ import annotations

from typing import Any

from core.components import Transform


def _zem_snapshot(snapshot: Any) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    if str(snapshot.get("kind", "")).strip().lower() != "zem_zev":
        return None
    return snapshot


def track_plot_events(
    *,
    actor_bots: dict[str, Any],
    ecs_world: Any,
    plotter: Any,
    events_seen: set[tuple[str, str]],
) -> None:
    for uid, bot in actor_bots.items():
        get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
        if not callable(get_snapshot):
            continue
        try:
            snapshot = _zem_snapshot(get_snapshot())
        except Exception:
            continue
        if snapshot is None:
            continue
        actor = ecs_world.get_entity_by_id(uid)
        if actor is None:
            continue
        trans = actor.get_component(Transform)
        if trans is None:
            continue
        for event_name, done_key, projected_dx_key in (
            ("setup_gate", "setup_gate_done", "setup_gate_projected_dx"),
            ("flare_gate", "terminal_gate_done", "terminal_gate_projected_dx"),
        ):
            if not bool(snapshot.get(done_key)):
                continue
            event_key = (uid, event_name)
            if event_key in events_seen:
                continue
            label = event_name.replace("_", " ")
            projected_dx = snapshot.get(projected_dx_key)
            try:
                projected_dx_val = float(projected_dx) if projected_dx is not None else None
            except (TypeError, ValueError):
                projected_dx_val = None
            if projected_dx_val is not None:
                label = f"{label} pdx={projected_dx_val:.1f}"
            if event_name == "setup_gate":
                apex_over_target = snapshot.get("setup_gate_projected_apex_over_target")
                try:
                    apex_over_target_val = (
                        float(apex_over_target) if apex_over_target is not None else None
                    )
                except (TypeError, ValueError):
                    apex_over_target_val = None
                if apex_over_target_val is not None:
                    label = f"{label} pax={apex_over_target_val:.1f}"
            plotter.mark_event(
                name=event_name,
                x=float(trans.pos.x),
                y=float(trans.pos.y),
                label=label,
            )
            events_seen.add(event_key)
