from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, cast

from game.core.trace_policy import (
    TRACE_DETAIL_DEBUG,
    TRACE_DETAIL_REPLAY,
    TRACE_DETAIL_REPORT,
    normalize_trace_detail,
)
from game.core.bot import (
    Bot,
    BotAction,
    BotDisplayState,
    BotEvalDecision,
    FlightPhaseSnapshot,
    resolve_bot_name,
)
from game.core.components import (
    ActorProfile,
    ContactReport,
    ControlIntent,
    Engine,
    FlightState,
    FuelTank,
    KinematicMotion,
    LandingSite,
    LandingSiteEconomy,
    LanderState,
    PhysicsState,
    PlayerControlled,
    PlayerSelectable,
    RefuelConfig,
    ScriptController,
    SensorReadings,
    SiteAttachment,
    Transform,
    Wallet,
)
from game.core.ecs import Entity, World
from bot_framework.eval.result_pipeline import _safe_phase_snapshot
from game.runtime.actor_registry import get_actor_control_role
from utils.plot import (
    _ballistic_curve_from_state,
    _build_plot_context,
    _curve_apex_point,
    _find_event,
    _idealized_reference_apex_y,
    _idealized_reference_curve,
    _projected_apex_point,
    _spatial_limits_with_target,
    _vx_corrected_ballistic_reference_curve,
    _vector_sample_indices,
)
from utils.tracebundle import sanitize_token

TRACEPACK_SCHEMA = "pylander.tracepack.v1"
RUN_TRACE_SCHEMA = "pylander.run_trace.v1"
TRACEPACK_SCHEMA_VERSION = 3
RUN_TRACE_SCHEMA_VERSION = 2


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value)
    return token if token else None


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _vector_payload(vec: Any) -> dict[str, float] | None:
    if vec is None:
        return None
    x = _safe_float(getattr(vec, "x", None))
    y = _safe_float(getattr(vec, "y", None))
    if x is None and y is None:
        return None
    return {
        "x": 0.0 if x is None else x,
        "y": 0.0 if y is None else y,
    }


def _display_state_payload(display: BotDisplayState | None) -> dict[str, Any] | None:
    if display is None:
        return None
    payload: dict[str, Any] = {}
    for key in ("bot_name", "mode", "phase", "summary", "detail"):
        value = getattr(display, key)
        if value is None:
            continue
        payload[key] = value
    return payload or None


def _phase_snapshot_payload(
    snapshot: FlightPhaseSnapshot | None,
) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    boost_cutoff = snapshot.boost_cutoff
    boost_cutoff_payload = None
    if boost_cutoff is not None:
        boost_cutoff_payload = {
            "time_s": _safe_float(boost_cutoff.time_s),
            "altitude": _safe_float(boost_cutoff.altitude),
            "x": _safe_float(boost_cutoff.x),
            "y": _safe_float(boost_cutoff.y),
            "vx": _safe_float(boost_cutoff.vx),
            "vy_up": _safe_float(boost_cutoff.vy_up),
            "projected_apex_y": _safe_float(boost_cutoff.projected_apex_y),
            "projected_apex_over_target": _safe_float(
                boost_cutoff.projected_apex_over_target
            ),
            "has_target_y_solution": _safe_bool(boost_cutoff.has_target_y_solution),
            "projected_dx": _safe_float(boost_cutoff.projected_dx),
            "projected_impact_dx": _safe_float(boost_cutoff.projected_impact_dx),
            "projected_impact_angle_deg": _safe_float(
                boost_cutoff.projected_impact_angle_deg
            ),
            "burn_duration_s": _safe_float(boost_cutoff.burn_duration_s),
            "burn_fuel_used": _safe_float(boost_cutoff.burn_fuel_used),
            "burn_avg_thrust_level": _safe_float(boost_cutoff.burn_avg_thrust_level),
        }
    return {
        "phase": snapshot.phase,
        "milestones": list(snapshot.milestones),
        "boost_cutoff": boost_cutoff_payload,
    }


def _safe_display_state(bot: Any) -> BotDisplayState | None:
    getter = getattr(bot, "get_display_state", None)
    if not callable(getter):
        return None
    try:
        display = getter()
    except Exception:
        return None
    return display if isinstance(display, BotDisplayState) else None


def _serialize_entity(entity: Entity, *, actor_bots: dict[str, Bot]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "uid": entity.uid,
        "active": bool(getattr(entity, "active", True)),
    }

    actor_profile = entity.get_component(ActorProfile)
    if actor_profile is not None:
        payload["profile"] = {
            "kind": actor_profile.kind,
            "name": actor_profile.name,
            "tags": list(actor_profile.tags),
        }
    payload["control_role"] = get_actor_control_role(entity)

    transform = entity.get_component(Transform)
    if transform is not None:
        payload["transform"] = {
            "x": float(transform.pos.x),
            "y": float(transform.pos.y),
            "rotation": float(transform.rotation),
            "scale": float(transform.scale),
        }

    physics = entity.get_component(PhysicsState)
    if physics is not None:
        payload["physics"] = {
            "vx": float(physics.vel.x),
            "vy": float(physics.vel.y),
            "ax": float(physics.acc.x),
            "ay": float(physics.acc.y),
            "mass": float(physics.mass),
        }

    fuel = entity.get_component(FuelTank)
    if fuel is not None:
        payload["fuel"] = {
            "fuel": float(fuel.fuel),
            "max_fuel": float(fuel.max_fuel),
            "density": float(fuel.density),
        }

    engine = entity.get_component(Engine)
    if engine is not None:
        payload["engine"] = {
            "thrust_level": float(engine.thrust_level),
            "target_thrust": float(engine.target_thrust),
            "target_angle": float(engine.target_angle),
            "min_thrust": float(engine.min_thrust),
            "max_thrust": float(engine.max_thrust),
            "max_power": float(engine.max_power),
            "base_burn_rate": float(engine.base_burn_rate),
            "overdrive_burn_multiplier": float(engine.overdrive_burn_multiplier),
            "max_rotation_rate": float(engine.max_rotation_rate),
        }

    lander_state = entity.get_component(LanderState)
    if lander_state is not None:
        state_value = lander_state.state
        payload["lander_state"] = {
            "state": str(
                state_value.value
                if isinstance(state_value, FlightState)
                else state_value
            ),
            "safe_landing_velocity": float(lander_state.safe_landing_velocity),
            "safe_landing_angle": float(lander_state.safe_landing_angle),
        }

    wallet = entity.get_component(Wallet)
    if wallet is not None:
        payload["wallet"] = {"credits": float(wallet.credits)}

    landing_site = entity.get_component(LandingSite)
    if landing_site is not None:
        payload["landing_site"] = {
            "size": float(landing_site.size),
            "terrain_mode": landing_site.terrain_mode,
            "terrain_bound": bool(landing_site.terrain_bound),
            "blend_margin": float(landing_site.blend_margin),
            "cut_depth": float(landing_site.cut_depth),
            "support_height": float(landing_site.support_height),
        }

    landing_site_economy = entity.get_component(LandingSiteEconomy)
    if landing_site_economy is not None:
        payload["landing_site_economy"] = {
            "award": float(landing_site_economy.award),
            "fuel_price": float(landing_site_economy.fuel_price),
            "visited": bool(landing_site_economy.visited),
        }

    kinematic = entity.get_component(KinematicMotion)
    if kinematic is not None:
        velocity_payload = _vector_payload(kinematic.velocity)
        if velocity_payload is not None:
            payload["kinematic_motion"] = {"velocity": velocity_payload}

    control_intent = entity.get_component(ControlIntent)
    if control_intent is not None:
        payload["control_intent"] = {
            "target_thrust": _safe_float(control_intent.target_thrust),
            "target_angle": _safe_float(control_intent.target_angle),
            "refuel_requested": bool(control_intent.refuel_requested),
        }

    script = entity.get_component(ScriptController)
    if script is not None:
        payload["script"] = {
            "loop": bool(script.loop),
            "enabled": bool(script.enabled),
            "frame_index": int(script.frame_index),
            "frame_elapsed": float(script.frame_elapsed),
            "frame_count": len(script.frames),
        }

    site_attachment = entity.get_component(SiteAttachment)
    if site_attachment is not None:
        payload["site_attachment"] = {
            "parent_uid": site_attachment.parent_uid,
            "local_offset": _vector_payload(site_attachment.local_offset),
        }

    refuel_config = entity.get_component(RefuelConfig)
    if refuel_config is not None:
        payload["refuel_config"] = {
            "refuel_rate": float(refuel_config.refuel_rate),
            "proximity_sensor_range": float(refuel_config.proximity_sensor_range),
        }

    sensor_readings = entity.get_component(SensorReadings)
    if sensor_readings is not None:
        payload["sensor_readings"] = {
            "radar_contact_count": len(sensor_readings.radar_contacts),
            "has_proximity": sensor_readings.proximity is not None,
        }

    contact_report = entity.get_component(ContactReport)
    if contact_report is not None:
        payload["contact_report"] = {
            "colliding": bool(contact_report.colliding),
            "normal": list(contact_report.normal)
            if contact_report.normal is not None
            else None,
            "rel_speed": float(contact_report.rel_speed),
            "point": list(contact_report.point)
            if contact_report.point is not None
            else None,
        }

    player_controlled = entity.get_component(PlayerControlled)
    if player_controlled is not None:
        payload["player_controlled"] = {"active": bool(player_controlled.active)}

    player_selectable = entity.get_component(PlayerSelectable)
    if player_selectable is not None:
        payload["player_selectable"] = {"order": int(player_selectable.order)}

    bot = actor_bots.get(entity.uid)
    if bot is not None:
        bot_name = _safe_str(resolve_bot_name(bot)) or type(bot).__name__
        payload["bot"] = {
            "name": bot_name,
            "display_state": _display_state_payload(_safe_display_state(bot)),
            "phase_snapshot": _phase_snapshot_payload(_safe_phase_snapshot(bot)),
        }

    return payload


def _terrain_payload_from_samples(
    terrain: Any,
    *,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = _build_plot_context(terrain, samples, target=target)
    return {
        "xs": [float(value) for value in ctx.terrain_xs],
        "ys": [float(value) for value in ctx.terrain_ys],
        "bounds": {
            "min_x": float(ctx.min_x),
            "max_x": float(ctx.max_x),
            "lower_y": float(ctx.lower_y),
            "upper_y": float(ctx.upper_y),
        },
    }


def _trace_primary_samples(
    snapshots: list[dict[str, Any]],
    *,
    primary_uid: str,
) -> list[tuple[float, float, float, float, float, float, float, float]]:
    samples: list[tuple[float, float, float, float, float, float, float, float]] = []
    for snapshot in snapshots:
        elapsed = _safe_float(snapshot.get("elapsed_time_s"))
        entities = snapshot.get("entities") or []
        if elapsed is None or not isinstance(entities, list):
            continue
        actor = next(
            (
                item
                for item in entities
                if isinstance(item, dict) and str(item.get("uid") or "") == primary_uid
            ),
            None,
        )
        if actor is None or not isinstance(actor, dict):
            continue
        transform = dict(actor.get("transform") or {})
        physics = dict(actor.get("physics") or {})
        engine = dict(actor.get("engine") or {})
        x = _safe_float(transform.get("x"))
        y = _safe_float(transform.get("y"))
        rotation = _safe_float(transform.get("rotation"))
        vx = _safe_float(physics.get("vx"))
        vy = _safe_float(physics.get("vy"))
        thrust = _safe_float(engine.get("thrust_level"))
        if (
            x is None
            or y is None
            or rotation is None
            or vx is None
            or vy is None
            or thrust is None
        ):
            continue
        x_val = cast(float, x)
        y_val = cast(float, y)
        rotation_val = cast(float, rotation)
        vx_val = cast(float, vx)
        vy_val = cast(float, vy)
        thrust_val = cast(float, thrust)
        speed = math.hypot(float(vx_val), float(vy_val))
        samples.append(
            (
                float(x_val),
                float(y_val),
                float(speed),
                float(thrust_val),
                float(rotation_val),
                float(elapsed),
                float(vx_val),
                float(vy_val),
            )
        )
    return samples


def _event_time(event: dict[str, Any]) -> float | None:
    time_s = _safe_float(event.get("time_s"))
    if time_s is not None:
        return time_s
    return _safe_float(event.get("elapsed_time_s"))


def _polyline_points(xs: list[Any], ys: list[Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for raw_x, raw_y in zip(xs, ys, strict=False):
        px = _safe_float(raw_x)
        py = _safe_float(raw_y)
        if px is None or py is None:
            continue
        point = (float(px), float(py))
        if (
            points
            and math.isclose(point[0], points[-1][0], abs_tol=1e-9)
            and math.isclose(point[1], points[-1][1], abs_tol=1e-9)
        ):
            continue
        points.append(point)
    return points


def _polyline_lengths(
    points: list[tuple[float, float]],
) -> tuple[list[float], float]:
    cumulative = [0.0]
    total = 0.0
    for idx in range(1, len(points)):
        seg_len = math.hypot(
            float(points[idx][0]) - float(points[idx - 1][0]),
            float(points[idx][1]) - float(points[idx - 1][1]),
        )
        total += seg_len
        cumulative.append(total)
    return cumulative, total


def _project_point_to_segment(
    *,
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], float, float]:
    seg_dx = float(end[0]) - float(start[0])
    seg_dy = float(end[1]) - float(start[1])
    seg_len_sq = (seg_dx * seg_dx) + (seg_dy * seg_dy)
    if seg_len_sq <= 1e-9:
        distance = math.hypot(
            float(point[0]) - float(start[0]), float(point[1]) - float(start[1])
        )
        return start, 0.0, distance
    mix = (
        ((float(point[0]) - float(start[0])) * seg_dx)
        + ((float(point[1]) - float(start[1])) * seg_dy)
    ) / seg_len_sq
    mix = max(0.0, min(1.0, mix))
    projected = (
        float(start[0]) + (seg_dx * mix),
        float(start[1]) + (seg_dy * mix),
    )
    distance = math.hypot(
        float(point[0]) - float(projected[0]),
        float(point[1]) - float(projected[1]),
    )
    return projected, mix, distance


def _project_point_to_polyline(
    *,
    point: tuple[float, float],
    polyline: list[tuple[float, float]],
) -> tuple[tuple[float, float], float]:
    best_projection = polyline[0]
    best_distance = math.hypot(
        float(point[0]) - float(best_projection[0]),
        float(point[1]) - float(best_projection[1]),
    )
    for idx in range(1, len(polyline)):
        projection, _mix, distance = _project_point_to_segment(
            point=point,
            start=polyline[idx - 1],
            end=polyline[idx],
        )
        if distance < best_distance:
            best_projection = projection
            best_distance = distance
    return best_projection, best_distance


def _reference_target_y(
    *,
    target_y: float,
    events: list[dict[str, Any]],
) -> float:
    success_event = _find_event(events, name="success")
    success_y = _safe_float((success_event or {}).get("y"))
    if success_y is None:
        return float(target_y)
    return float(success_y)


def _reference_gap_metrics(
    *,
    actual_xs: list[Any],
    actual_ys: list[Any],
    reference_curve: dict[str, Any] | None,
) -> dict[str, float] | None:
    if not isinstance(reference_curve, dict):
        return None
    actual_points = _polyline_points(actual_xs, actual_ys)
    reference_points = _polyline_points(
        list(reference_curve.get("xs") or []),
        list(reference_curve.get("ys") or []),
    )
    if len(actual_points) < 2 or len(reference_points) < 2:
        return None
    actual_cumulative, actual_length = _polyline_lengths(actual_points)
    if actual_length <= 1e-9:
        return None

    gaps: list[float] = []
    for point in actual_points:
        _projection, distance = _project_point_to_polyline(
            point=point,
            polyline=reference_points,
        )
        gaps.append(float(distance))
    if len(gaps) < 2:
        return None

    gap_area = sum(
        0.5
        * (gaps[idx] + gaps[idx + 1])
        * (actual_cumulative[idx + 1] - actual_cumulative[idx])
        for idx in range(len(gaps) - 1)
    )
    gap_mean = gap_area / actual_length
    return {
        "gap_mean": float(gap_mean),
        "gap_area": float(gap_area),
        "gap_max": float(max(gaps)),
    }


def _derive_plot_payload(
    terrain: Any,
    *,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    events: list[dict[str, Any]],
    target: dict[str, Any] | None,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not samples:
        return None
    ctx = _build_plot_context(terrain, samples, target=target)
    terrain_payload = {
        "xs": [float(value) for value in ctx.terrain_xs],
        "ys": [float(value) for value in ctx.terrain_ys],
    }
    event_payloads = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_payloads.append(
            {
                "name": _safe_str(event.get("name")) or "event",
                "label": _safe_str(event.get("label")),
                "x": _safe_float(event.get("x")),
                "y": _safe_float(event.get("y")),
                "time_s": _event_time(event),
                "metadata": {
                    str(key): value
                    for key, value in event.items()
                    if isinstance(key, str)
                    and key
                    not in {"name", "label", "x", "y", "time_s", "elapsed_time_s"}
                },
            }
        )

    apex_actual = _curve_apex_point(ctx.xs, ctx.ys)
    apex_projected = _projected_apex_point(ctx, target=target, events=events)
    vector_indices = _vector_sample_indices(ctx.sample_times)
    ballistic_curve = None
    reference_curve = None
    reference_metrics = None
    reference_apex_y = None
    reference_kind = ""
    reference_label = ""
    if target is not None:
        target_x = _safe_float(target.get("x"))
        target_y = _safe_float(target.get("y"))
        if target_x is not None and target_y is not None:
            reference_target_y = _reference_target_y(
                target_y=float(target_y),
                events=events,
            )
            level_name = str((identity or {}).get("level") or "").strip().lower()
            boost_cutoff_event = _find_event(events, name="boost_cutoff")
            if boost_cutoff_event is not None:
                cutoff_x = _safe_float(boost_cutoff_event.get("x"))
                cutoff_y = _safe_float(boost_cutoff_event.get("y"))
                cutoff_vx = _safe_float(boost_cutoff_event.get("vx"))
                cutoff_vy_up = _safe_float(boost_cutoff_event.get("vy_up"))
                if (
                    cutoff_x is not None
                    and cutoff_y is not None
                    and cutoff_vx is not None
                    and cutoff_vy_up is not None
                ):
                    cutoff_x_val = cast(float, cutoff_x)
                    cutoff_y_val = cast(float, cutoff_y)
                    cutoff_vx_val = cast(float, cutoff_vx)
                    cutoff_vy_up_val = cast(float, cutoff_vy_up)
                    ballistic_xs, ballistic_ys, has_target_y_solution = (
                        _ballistic_curve_from_state(
                            x=float(cutoff_x_val),
                            y=float(cutoff_y_val),
                            vx=float(cutoff_vx_val),
                            vy_up=float(cutoff_vy_up_val),
                            target_x=float(target_x),
                            target_y=float(target_y),
                        )
                    )
                    if has_target_y_solution:
                        ballistic_curve = {
                            "xs": [float(value) for value in ballistic_xs],
                            "ys": [float(value) for value in ballistic_ys],
                            "has_target_y_solution": True,
                            "source": "boost_cutoff",
                        }
            if level_name == "terminal":
                corrected_curve = _vx_corrected_ballistic_reference_curve(
                    start_x=float(ctx.xs[0]),
                    start_y=float(ctx.ys[0]),
                    vx=float(ctx.vxs[0]),
                    vy_up=float(ctx.vys[0]),
                    target_x=float(target_x),
                    target_y=float(reference_target_y),
                )
                if corrected_curve is not None:
                    ref_xs, ref_ys = corrected_curve
                    reference_curve = {
                        "xs": [float(value) for value in ref_xs],
                        "ys": [float(value) for value in ref_ys],
                        "kind": "ballistic_vx_adjusted",
                        "label": "ballistic ref (vx adjusted)",
                    }
                    reference_kind = "ballistic_vx_adjusted"
                    reference_label = "ballistic ref (vx adjusted)"
            else:
                downhill_policy = (
                    "exit_angle"
                    if level_name == "boost" and float(target_y) < float(ctx.ys[0])
                    else "descent_angle"
                )
                reference_apex_y = _idealized_reference_apex_y(
                    start_x=ctx.xs[0],
                    start_y=ctx.ys[0],
                    target_x=float(target_x),
                    target_y=float(reference_target_y),
                    downhill_policy=downhill_policy,
                    min_exit_angle_deg=45.0,
                )
                ref_curve = _idealized_reference_curve(
                    start_x=ctx.xs[0],
                    start_y=ctx.ys[0],
                    target_x=float(target_x),
                    target_y=float(reference_target_y),
                    apex_y=float(reference_apex_y),
                )
                if ref_curve is not None:
                    ref_xs, ref_ys = ref_curve
                    reference_curve = {
                        "xs": [float(value) for value in ref_xs],
                        "ys": [float(value) for value in ref_ys],
                        "apex_y": float(reference_apex_y),
                        "kind": "idealized",
                        "label": "idealized reference",
                    }
                    reference_kind = "idealized"
                    reference_label = "idealized reference"
    if reference_curve is not None:
        reference_metrics = _reference_gap_metrics(
            actual_xs=[float(value) for value in ctx.xs],
            actual_ys=[float(value) for value in ctx.ys],
            reference_curve=reference_curve,
        )

    overlay_points: list[tuple[float, float]] = []
    if apex_actual is not None:
        overlay_points.append(apex_actual)
    if apex_projected is not None:
        overlay_points.append(apex_projected)
    overlay_curves: list[dict[str, Any]] = []
    for curve in (ballistic_curve, reference_curve):
        if not isinstance(curve, dict):
            continue
        overlay_curves.append(curve)
        curve_apex = _curve_apex_point(
            [float(value) for value in curve.get("xs") or []],
            [float(value) for value in curve.get("ys") or []],
        )
        if curve_apex is not None:
            overlay_points.append(curve_apex)
    min_x, max_x, lower_y, upper_y = _spatial_limits_with_target(
        ctx,
        target=dict(target or {}) or None,
        extra_points=overlay_points or None,
        overlay_curves=overlay_curves or None,
    )

    return {
        "terrain": terrain_payload,
        "target": dict(target or {}) or None,
        "events": event_payloads,
        "bounds": {
            "min_x": float(min_x),
            "max_x": float(max_x),
            "lower_y": float(lower_y),
            "upper_y": float(upper_y),
            "span_x": float(max_x - min_x),
            "span_y": float(upper_y - lower_y),
        },
        "samples": {
            "time_s": [float(value) for value in ctx.sample_times],
            "x": [float(value) for value in ctx.xs],
            "y": [float(value) for value in ctx.ys],
            "speed": [float(value) for value in ctx.speeds],
            "thrust": [float(value) for value in ctx.thrusts],
            "angle": [float(value) for value in ctx.angles],
            "vx": [float(value) for value in ctx.vxs],
            "vy": [float(value) for value in ctx.vys],
        },
        "vector_sample_indices": [int(value) for value in vector_indices],
        "actual_apex": None
        if apex_actual is None
        else {"x": float(apex_actual[0]), "y": float(apex_actual[1])},
        "projected_apex": None
        if apex_projected is None
        else {"x": float(apex_projected[0]), "y": float(apex_projected[1])},
        "ballistic_curve": ballistic_curve,
        "reference_curve": reference_curve,
        "reference_metrics": reference_metrics,
        "reference_kind": reference_kind or None,
        "reference_label": reference_label or None,
    }


def _write_preview_png(
    plot_payload: dict[str, Any],
    *,
    out_path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    terrain = dict(plot_payload.get("terrain") or {})
    samples = dict(plot_payload.get("samples") or {})
    reference_curve = dict(plot_payload.get("reference_curve") or {})
    bounds = dict(plot_payload.get("bounds") or {})
    target = dict(plot_payload.get("target") or {})
    events = list(plot_payload.get("events") or [])

    fig, ax = plt.subplots(figsize=(2.6, 1.5), dpi=100)
    fig.patch.set_facecolor("#faf7ef")
    ax.set_facecolor("#faf7ef")
    ax.plot(
        terrain.get("xs") or [],
        terrain.get("ys") or [],
        color="#746651",
        linewidth=1.0,
        alpha=0.9,
    )
    ref_xs = reference_curve.get("xs") or []
    ref_ys = reference_curve.get("ys") or []
    if ref_xs and ref_ys:
        ax.plot(
            ref_xs,
            ref_ys,
            color="#ff8a00",
            linewidth=1.8,
            alpha=0.96,
            linestyle="--",
            dash_capstyle="round",
        )
    ax.plot(
        samples.get("x") or [],
        samples.get("y") or [],
        color="#0057d8",
        linewidth=2.0,
        alpha=0.99,
        solid_capstyle="round",
    )
    if target:
        target_x = _safe_float(target.get("x"))
        target_y = _safe_float(target.get("y"))
        target_size = abs(_safe_float(target.get("size")) or 0.0)
        if target_x is not None and target_y is not None:
            half_width = max(10.0, 0.5 * target_size)
            ax.plot(
                [float(target_x) - half_width, float(target_x) + half_width],
                [float(target_y), float(target_y)],
                color="#2ecc71",
                linewidth=2.2,
                solid_capstyle="round",
            )
    for event in events:
        event_name = str(event.get("name") or "")
        if event_name not in {"success", "crash", "out_of_fuel"}:
            continue
        event_x = _safe_float(event.get("x"))
        event_y = _safe_float(event.get("y"))
        if event_x is None or event_y is None:
            continue
        event_x_val = cast(float, event_x)
        event_y_val = cast(float, event_y)
        color = "#2ecc71" if event_name == "success" else "#d62728"
        ax.scatter(
            [float(event_x_val)], [float(event_y_val)], s=12.0, color=color, zorder=5
        )

    min_x = _safe_float(bounds.get("min_x"))
    max_x = _safe_float(bounds.get("max_x"))
    lower_y = _safe_float(bounds.get("lower_y"))
    upper_y = _safe_float(bounds.get("upper_y"))
    if (
        min_x is not None
        and max_x is not None
        and lower_y is not None
        and upper_y is not None
    ):
        min_x_val = cast(float, min_x)
        max_x_val = cast(float, max_x)
        lower_y_val = cast(float, lower_y)
        upper_y_val = cast(float, upper_y)
        ax.set_xlim(float(min_x_val), float(max_x_val))
        ax.set_ylim(float(lower_y_val), float(upper_y_val))
    ax.axis("off")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


class TraceRecorder:
    def __init__(
        self,
        terrain: Any,
        ecs_world: World,
        actor_bots: dict[str, Bot],
        active_uid_getter: Callable[[], str],
        *,
        enabled: bool = False,
        sample_period_s: float = 0.25,
        detail: str = TRACE_DETAIL_REPORT,
        outputs_root: str | Path = "outputs",
    ) -> None:
        self.enabled = bool(enabled)
        self.terrain = terrain
        self.ecs_world = ecs_world
        self.actor_bots = actor_bots
        self.active_uid_getter = active_uid_getter
        self.outputs_root = Path(outputs_root).resolve()
        self._selector_tag = "run"
        self._trace_root_dir: Path | None = None
        self._sample_period_s = max(0.05, float(sample_period_s))
        self._trace_detail = normalize_trace_detail(detail, default=TRACE_DETAIL_REPORT)
        self._time_accum = 0.0
        self._sample_time_s = 0.0
        self._snapshots: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._control_log: list[dict[str, Any]] = []
        self._target: dict[str, Any] | None = None
        self._identity: dict[str, Any] = {}
        self._primary_uid: str | None = None

    def set_selector_tag(self, tag: str) -> None:
        self._selector_tag = sanitize_token(tag)

    def set_trace_root_dir(self, path: str | Path | None) -> None:
        self._trace_root_dir = None if path is None else Path(path).resolve()

    def set_sample_period_s(self, value: float) -> None:
        self._sample_period_s = max(0.05, float(value))

    def set_trace_detail(self, value: str) -> None:
        self._trace_detail = normalize_trace_detail(value, default=TRACE_DETAIL_REPORT)

    def _control_log_enabled(self) -> bool:
        return self._trace_detail in {TRACE_DETAIL_REPLAY, TRACE_DETAIL_DEBUG}

    def _debug_bot_action_enabled(self) -> bool:
        return self._trace_detail == TRACE_DETAIL_DEBUG

    def _include_entity_catalog(self) -> bool:
        return self._trace_detail in {TRACE_DETAIL_REPLAY, TRACE_DETAIL_DEBUG}

    def set_identity(
        self,
        *,
        level_name: str,
        scenario_name: str | None,
        seed: int | None,
        bot_name: str | None,
        eval_goal: str,
    ) -> None:
        self._identity = {
            "level": level_name,
            "scenario": scenario_name,
            "seed": seed,
            "bot": bot_name,
            "eval_goal": eval_goal,
        }

    def set_target(
        self,
        *,
        x: float,
        y: float,
        label: str = "target",
        size: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        self._target = {
            "x": float(x),
            "y": float(y),
            "label": str(label),
            "size": None if size is None else float(size),
        }

    def seed_initial_sample(self) -> None:
        if not self.enabled:
            return
        self._snapshots.clear()
        self._events.clear()
        self._control_log.clear()
        self._sample_time_s = 0.0
        self._time_accum = 0.0
        self._primary_uid = self.active_uid_getter()
        self.capture_snapshot(elapsed_time_s=0.0, frame_dt_s=0.0)

    def update(self, dt: float, *, elapsed_time_s: float) -> None:
        if not self.enabled:
            return
        self._time_accum += float(dt)
        if self._time_accum < self._sample_period_s:
            return
        self._time_accum = math.fmod(self._time_accum, self._sample_period_s)
        self.capture_snapshot(
            elapsed_time_s=float(elapsed_time_s), frame_dt_s=float(dt)
        )

    def capture_snapshot(self, *, elapsed_time_s: float, frame_dt_s: float) -> None:
        if not self.enabled:
            return
        self._sample_time_s = float(elapsed_time_s)
        snapshot = {
            "elapsed_time_s": self._sample_time_s,
            "frame_dt_s": float(frame_dt_s),
            "active_uid": self.active_uid_getter(),
            "entities": [
                _serialize_entity(entity, actor_bots=self.actor_bots)
                for entity in self.ecs_world.entities
            ],
        }
        self._snapshots.append(snapshot)

    def record_bot_action(
        self,
        *,
        uid: str,
        elapsed_time_s: float,
        bot_dt_s: float,
        sensors: Any,
        action: BotAction,
        passive_s: float,
        update_s: float,
        bot: Bot,
    ) -> None:
        if not self.enabled or not self._debug_bot_action_enabled():
            return
        self._control_log.append(
            {
                "kind": "bot_action",
                "uid": uid,
                "elapsed_time_s": float(elapsed_time_s),
                "bot_dt_s": float(bot_dt_s),
                "sensors": {
                    "x": float(getattr(sensors, "x", 0.0)),
                    "y": float(getattr(sensors, "y", 0.0)),
                    "altitude": float(getattr(sensors, "altitude", 0.0)),
                    "terrain_y": float(getattr(sensors, "terrain_y", 0.0)),
                    "terrain_slope": float(getattr(sensors, "terrain_slope", 0.0)),
                    "vx": float(getattr(sensors, "vx", 0.0)),
                    "vy_up": float(getattr(sensors, "vy_up", 0.0)),
                    "angle": float(getattr(sensors, "angle", 0.0)),
                    "ax": float(getattr(sensors, "ax", 0.0)),
                    "ay_up": float(getattr(sensors, "ay_up", 0.0)),
                    "mass": float(getattr(sensors, "mass", 0.0)),
                    "thrust_level": float(getattr(sensors, "thrust_level", 0.0)),
                    "fuel": float(getattr(sensors, "fuel", 0.0)),
                    "state": str(getattr(sensors, "state", "")),
                },
                "action": {
                    "target_thrust": float(action.target_thrust),
                    "target_angle": float(action.target_angle),
                    "refuel": bool(action.refuel),
                    "status": action.status,
                    "message": action.message,
                },
                "display_state": _display_state_payload(_safe_display_state(bot)),
                "phase_snapshot": _phase_snapshot_payload(_safe_phase_snapshot(bot)),
                "profile": {
                    "passive_ms": float(passive_s * 1000.0),
                    "update_ms": float(update_s * 1000.0),
                },
            }
        )

    def record_controls_map(
        self,
        *,
        elapsed_time_s: float,
        controls_by_uid: dict[str, tuple[float, float, bool] | None],
    ) -> None:
        if not self.enabled or not self._control_log_enabled():
            return
        serialized: dict[str, Any] = {}
        for uid, control in controls_by_uid.items():
            if control is None:
                serialized[uid] = None
                continue
            serialized[uid] = {
                "target_thrust": float(control[0]),
                "target_angle": float(control[1]),
                "refuel": bool(control[2]),
            }
        self._control_log.append(
            {
                "kind": "routed_controls",
                "elapsed_time_s": float(elapsed_time_s),
                "controls_by_uid": serialized,
            }
        )

    def mark_event(
        self,
        *,
        name: str,
        x: float,
        y: float,
        label: str | None = None,
        metadata: dict[str, float | str | None] | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload: dict[str, Any] = {
            "name": str(name),
            "x": float(x),
            "y": float(y),
        }
        if label is not None:
            payload["label"] = str(label)
        for key, value in (metadata or {}).items():
            if not isinstance(key, str):
                continue
            payload[key] = value
        self._events.append(payload)
        if self._control_log_enabled():
            self._control_log.append(
                {
                    "kind": "event",
                    "elapsed_time_s": _event_time(payload)
                    if _event_time(payload) is not None
                    else self._sample_time_s,
                    "event": dict(payload),
                }
            )

    def record_eval_decision(
        self, *, elapsed_time_s: float, decision: BotEvalDecision
    ) -> None:
        if not self.enabled or not self._control_log_enabled():
            return
        self._control_log.append(
            {
                "kind": "eval_decision",
                "elapsed_time_s": float(elapsed_time_s),
                "decision": {
                    "should_end": bool(decision.should_end),
                    "success": decision.success,
                    "failure_mode": decision.failure_mode,
                    "end_reason": decision.end_reason,
                    "metrics": dict(decision.metrics),
                },
            }
        )

    def _build_outcome_event(self, *, elapsed_time_s: float) -> dict[str, Any] | None:
        active_actor = self.ecs_world.get_entity_by_id(self.active_uid_getter())
        if active_actor is None:
            return None
        lander_state = active_actor.get_component(LanderState)
        transform = active_actor.get_component(Transform)
        fuel = active_actor.get_component(FuelTank)
        if lander_state is None or transform is None:
            return None
        state_name = str(
            lander_state.state.value
            if isinstance(lander_state.state, FlightState)
            else lander_state.state
        )
        if (
            state_name not in {"landed", "crashed"}
            and fuel is not None
            and fuel.fuel <= 0.0
        ):
            state_name = "out_of_fuel"
        event_name = None
        if state_name == "landed":
            event_name = "success"
        elif state_name == "crashed":
            event_name = "crash"
        elif state_name == "out_of_fuel":
            event_name = "out_of_fuel"
        if event_name is None:
            return None
        return {
            "name": event_name,
            "label": state_name,
            "x": float(transform.pos.x),
            "y": float(transform.pos.y),
            "time_s": float(elapsed_time_s),
        }

    def finalize(
        self, *, result: dict[str, Any], elapsed_time_s: float
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        if self._primary_uid is None:
            self._primary_uid = self.active_uid_getter()
        if not self._snapshots:
            self.capture_snapshot(elapsed_time_s=float(elapsed_time_s), frame_dt_s=0.0)
        elif (
            abs(
                float(self._snapshots[-1].get("elapsed_time_s") or 0.0)
                - float(elapsed_time_s)
            )
            > 1e-6
        ):
            self.capture_snapshot(elapsed_time_s=float(elapsed_time_s), frame_dt_s=0.0)
        outcome_event = self._build_outcome_event(elapsed_time_s=float(elapsed_time_s))
        if outcome_event is not None:
            self._events.append(outcome_event)
            if self._control_log_enabled():
                self._control_log.append(
                    {
                        "kind": "outcome",
                        "elapsed_time_s": float(elapsed_time_s),
                        "event": dict(outcome_event),
                    }
                )

        primary_uid = self._primary_uid or self.active_uid_getter()
        samples = _trace_primary_samples(self._snapshots, primary_uid=primary_uid)
        plot_payload = _derive_plot_payload(
            self.terrain,
            samples=samples,
            events=self._events,
            target=self._target,
            identity=self._identity,
        )
        reference_metrics = dict((plot_payload or {}).get("reference_metrics") or {})
        trace_metric_extras: dict[str, float] = {}
        for source_key, result_key in (
            ("gap_mean", "trace_ref_gap_mean"),
            ("gap_area", "trace_ref_gap_area"),
            ("gap_max", "trace_ref_gap_max"),
        ):
            metric_value = _safe_float(reference_metrics.get(source_key))
            if metric_value is None:
                continue
            trace_metric_extras[result_key] = float(metric_value)
        terrain_payload = (
            _terrain_payload_from_samples(
                self.terrain, samples=samples, target=self._target
            )
            if samples
            else None
        )
        final_result_payload = {
            key: value
            for key, value in result.items()
            if isinstance(key, str) and not key.startswith("_")
        }
        final_result_payload.update(trace_metric_extras)
        trace_payload = {
            "schema": RUN_TRACE_SCHEMA,
            "schema_version": RUN_TRACE_SCHEMA_VERSION,
            "selector_tag": self._selector_tag,
            "trace_sample_period_s": float(self._sample_period_s),
            "trace_detail": self._trace_detail,
            "primary_uid": primary_uid,
            "identity": dict(self._identity),
            "target": dict(self._target or {}) or None,
            "terrain_profile": terrain_payload,
            "snapshots": list(self._snapshots),
            "events": list(self._events),
            "plot": plot_payload,
            "final_result": final_result_payload,
        }
        if self._include_entity_catalog():
            trace_payload["entity_catalog"] = [
                _serialize_entity(entity, actor_bots=self.actor_bots)
                for entity in self.ecs_world.entities
            ]
        if self._control_log_enabled():
            trace_payload["control_log"] = list(self._control_log)

        trace_root_dir = self._trace_root_dir
        if trace_root_dir is None:
            trace_root_dir = (
                self.outputs_root / "traces" / self._selector_tag
            ).resolve()
        trace_path = (
            trace_root_dir / "traces" / f"{self._selector_tag}.trace.json"
        ).resolve()
        preview_path = (
            trace_root_dir / "previews" / f"{self._selector_tag}.png"
        ).resolve()
        _json_write(trace_path, trace_payload)
        if plot_payload is not None:
            _write_preview_png(plot_payload, out_path=preview_path)

        trace_rel_path = None
        preview_rel_path = None
        try:
            trace_rel_path = trace_path.relative_to(self.outputs_root).as_posix()
        except ValueError:
            trace_rel_path = None
        try:
            preview_rel_path = preview_path.relative_to(self.outputs_root).as_posix()
        except ValueError:
            preview_rel_path = None

        return {
            **trace_metric_extras,
            "trace_path": str(trace_path),
            "trace_rel_path": trace_rel_path,
            "trace_preview_path": str(preview_path) if preview_path.exists() else None,
            "trace_preview_rel_path": preview_rel_path
            if preview_path.exists()
            else None,
            "trace_schema_version": RUN_TRACE_SCHEMA_VERSION,
            "trace_sample_period_s": float(self._sample_period_s),
            "trace_detail": self._trace_detail,
            "trace_snapshot_count": len(self._snapshots),
            "trace_event_count": len(self._events),
            "trace_control_log_count": len(self._control_log),
        }
