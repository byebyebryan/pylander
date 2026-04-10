"""Headless trajectory plotting utilities."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bot_framework.bots.common_ballistics import (
    ballistic_apex_from_state,
    estimate_target_y_projection,
    time_to_target_y_crossing,
)
from game.core.components import Engine, FuelTank, LanderState, PhysicsState, Transform
from game.core.config import GRAVITY_MAG
from game.core.ecs import require_component
from utils.tracebundle import sanitize_token


PlotMode = Literal["none", "speed", "thrust", "all"]
PlotOutputProfile = Literal["combined", "split", "both"]
_TALL_SPATIAL_RATIO_CUTOFF = 1.35
_EVENT_DISPLAY_NAMES: dict[str, str] = {
    "boost_cutoff": "boost",
    "terminal_gate": "terminal",
    "terminal_entry": "terminal",
    "success": "landed",
    "crash": "crash",
    "out_of_fuel": "fuel out",
}
_EVENT_COLORS: dict[str, str] = {
    "boost_cutoff": "#1f77b4",
    "terminal_gate": "#ff7f0e",
    "terminal_entry": "#ff7f0e",
    "success": "#2ecc71",
    "crash": "#d62728",
    "out_of_fuel": "#8c564b",
}
_EVENT_MARKERS: dict[str, str] = {
    "boost_cutoff": "o",
    "terminal_gate": "D",
    "terminal_entry": "D",
    "success": "*",
    "crash": "X",
    "out_of_fuel": "X",
}
_TIMESERIES_GATE_EVENT_NAMES: tuple[str, ...] = (
    "boost_cutoff",
    "terminal_gate",
    "terminal_entry",
    "out_of_fuel",
)


@dataclass
class _PlotContext:
    xs: list[float]
    ys: list[float]
    speeds: list[float]
    thrusts: list[float]
    angles: list[float]
    sample_times: list[float]
    vxs: list[float]
    vys: list[float]
    terrain_xs: list[float]
    terrain_ys: list[float]
    min_x: float
    max_x: float
    lower_y: float
    upper_y: float
    span_x: float
    span_y: float
    points: Any
    segments: Any
    speed_seg_vals: Any
    thrust_seg_vals: Any
    speed_arr: Any
    thrust_arr: Any
    angle_arr: Any


@dataclass(frozen=True)
class _ProjectedIntercept:
    end_x: float
    end_y: float
    miss_dx: float
    t_end: float
    has_target_y_solution: bool


@dataclass(frozen=True)
class _IdealizedReferenceKinematics:
    flight_t: float
    vx: float
    vy_up: float


def _collision_safe_path(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _collision_safe_dir(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.name}_{idx}")
        if not candidate.exists():
            return candidate
        idx += 1


def _compute_figure_size(
    span_x: float,
    span_y: float,
    *,
    layout: Literal["single", "all", "series"],
    arrangement: Literal["rows", "columns"] = "rows",
) -> tuple[float, float]:
    ratio = max(1e-6, span_x) / max(1e-6, span_y)
    panel_aspect = max(0.55, min(4.8, ratio))
    panel_area = 60.0
    min_width = 7.8 if ratio < _TALL_SPATIAL_RATIO_CUTOFF else 10.2
    min_height = 5.8 if ratio < _TALL_SPATIAL_RATIO_CUTOFF else 6.3
    width = max(min_width, min(26.0, (panel_area * panel_aspect) ** 0.5))
    height = max(min_height, min(16.0, panel_area / width))
    if layout == "all":
        if arrangement == "columns":
            panel_width = max(9.2, width)
            return max(15.0, min(26.0, panel_width * 2.15)), max(
                18.8, min(31.5, (height * 2.0) + 9.4)
            )
        return max(10.2, width), max(26.9, min(37.5, (height * 4.0) + 8.4))
    if layout == "series":
        return max(10.0, min(24.0, width * 1.1)), 3.6
    return width, height


def _spatial_ratio(span_x: float, span_y: float) -> float:
    return max(1e-6, span_x) / max(1e-6, span_y)


def _is_tall_spatial(span_x: float, span_y: float) -> bool:
    return _spatial_ratio(span_x, span_y) < _TALL_SPATIAL_RATIO_CUTOFF


def _combined_spatial_arrangement(
    span_x: float, span_y: float
) -> Literal["rows", "columns"]:
    return "columns" if _is_tall_spatial(span_x, span_y) else "rows"


def _spatial_colorbar_position(
    span_x: float, span_y: float
) -> Literal["right", "bottom"]:
    return "bottom" if _is_tall_spatial(span_x, span_y) else "right"


def _expand_span(lower: float, upper: float, *, min_span: float) -> tuple[float, float]:
    span = max(0.0, upper - lower)
    if span >= min_span:
        return lower, upper
    center = 0.5 * (lower + upper)
    half = 0.5 * min_span
    return center - half, center + half


def _resolve_dpi(
    fig_w: float,
    fig_h: float,
    *,
    base_dpi: int,
    max_side_px: int,
) -> int:
    long_side_in = max(1e-6, float(fig_w), float(fig_h))
    cap = int(max(1.0, float(max_side_px) / long_side_in))
    return max(24, min(int(base_dpi), cap))


def _build_plot_context(
    terrain,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    *,
    target: dict[str, float | str | None] | None = None,
) -> _PlotContext:
    if len(samples) < 2:
        if samples:
            samples = samples + [samples[-1]]
        else:
            samples = [
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            ]

    xs = [p[0] for p in samples]
    ys = [p[1] for p in samples]
    speeds = [p[2] for p in samples]
    thrusts = [p[3] for p in samples]
    angles = [p[4] for p in samples]
    sample_times = [p[5] for p in samples]
    vxs = [float(p[6]) if len(p) > 6 else 0.0 for p in samples]
    vys = [float(p[7]) if len(p) > 7 else 0.0 for p in samples]

    sample_min_x = min(xs)
    sample_max_x = max(xs)
    sample_span_x = max(1.0, sample_max_x - sample_min_x)
    x_pad = min(240.0, max(45.0, sample_span_x * 0.18))
    min_x = sample_min_x - x_pad
    max_x = sample_max_x + x_pad
    if target is not None:
        try:
            target_x = float(target.get("x", 0.0) or 0.0)
            target_size = abs(float(target.get("size", 0.0) or 0.0))
        except (TypeError, ValueError):
            target_x = 0.0
            target_size = 0.0
        start_x = float(xs[0])
        half_width = max(18.0, 0.5 * target_size)
        route_min_x = min(start_x, target_x - half_width)
        route_max_x = max(start_x, target_x + half_width)
        route_span_x = max(1.0, route_max_x - route_min_x)
        route_pad = min(240.0, max(45.0, route_span_x * 0.18))
        min_x = min(min_x, route_min_x - route_pad)
        max_x = max(max_x, route_max_x + route_pad)
    if max_x <= min_x:
        max_x = min_x + 1.0

    base_interval = terrain.get_resolution(0)
    import math as _math

    start_x = _math.floor(min_x / base_interval) * base_interval
    end_x = _math.ceil(max_x / base_interval) * base_interval
    terrain_xs: list[float] = []
    xx = start_x
    while xx <= end_x:
        terrain_xs.append(xx)
        xx += base_interval
    terrain_ys = [terrain(x, lod=0) for x in terrain_xs]

    all_y = terrain_ys + ys
    y_min = min(all_y)
    y_max = max(all_y)
    sample_span_y = max(1.0, y_max - y_min)
    y_pad = min(240.0, max(35.0, sample_span_y * 0.12))
    lower_y = y_min - y_pad
    upper_y = y_max + y_pad
    span_x = max_x - min_x
    span_y = upper_y - lower_y
    raw_ratio = span_x / max(1e-6, span_y)
    min_ratio = 1.25 if raw_ratio < _TALL_SPATIAL_RATIO_CUTOFF else 0.6
    max_ratio = 3.2
    if raw_ratio > max_ratio:
        lower_y, upper_y = _expand_span(lower_y, upper_y, min_span=span_x / max_ratio)
    elif raw_ratio < min_ratio:
        min_x, max_x = _expand_span(min_x, max_x, min_span=span_y * min_ratio)
    span_x = max_x - min_x
    span_y = upper_y - lower_y

    import numpy as np

    points = np.column_stack([xs, ys])
    segments = np.stack([points[:-1], points[1:]], axis=1)
    thrust_arr = np.array(thrusts, dtype=float)
    speed_arr = np.array(speeds, dtype=float)
    angle_arr = np.array(angles, dtype=float)
    speed_seg_vals = 0.5 * (speed_arr[:-1] + speed_arr[1:])
    thrust_seg_vals = 0.5 * (thrust_arr[:-1] + thrust_arr[1:])

    return _PlotContext(
        xs=xs,
        ys=ys,
        speeds=speeds,
        thrusts=thrusts,
        angles=angles,
        sample_times=sample_times,
        vxs=vxs,
        vys=vys,
        terrain_xs=terrain_xs,
        terrain_ys=terrain_ys,
        min_x=min_x,
        max_x=max_x,
        lower_y=lower_y,
        upper_y=upper_y,
        span_x=span_x,
        span_y=span_y,
        points=points,
        segments=segments,
        speed_seg_vals=speed_seg_vals,
        thrust_seg_vals=thrust_seg_vals,
        speed_arr=speed_arr,
        thrust_arr=thrust_arr,
        angle_arr=angle_arr,
    )


def _draw_events(ax, *, events: list[dict[str, float | str | None]] | None) -> None:
    event_list = list(events or [])
    if not event_list:
        return
    labeled_kinds: set[str] = set()
    for event in event_list:
        raw_name = event.get("name")
        event_name = (
            str(raw_name) if isinstance(raw_name, str) and raw_name else "event"
        )
        event_x = float(event.get("x", 0.0) or 0.0)
        event_y = float(event.get("y", 0.0) or 0.0)
        color = _EVENT_COLORS.get(event_name, "#222222")
        legend_label = _EVENT_DISPLAY_NAMES.get(
            event_name, event_name.replace("_", " ")
        )
        scatter_label = legend_label if event_name not in labeled_kinds else None
        labeled_kinds.add(event_name)
        ax.scatter(
            [event_x],
            [event_y],
            s=64.0 if event_name == "success" else 48.0,
            marker=_EVENT_MARKERS.get(event_name, "o"),
            color=color,
            edgecolors="#FFFFFF",
            linewidths=1.0,
            zorder=6,
            label=scatter_label,
        )
        raw_label = event.get("label")
        text_label = (
            str(raw_label) if isinstance(raw_label, str) and raw_label else legend_label
        )
        ax.annotate(
            text_label,
            xy=(event_x, event_y),
            xytext=(5, 6),
            textcoords="offset points",
            fontsize=7,
            color=color,
            zorder=7,
        )


def _sorted_gate_events(
    events: list[dict[str, float | str | None]] | None,
) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    seen: set[tuple[str, float]] = set()
    for event in events or []:
        raw_name = event.get("name")
        event_name = str(raw_name) if isinstance(raw_name, str) and raw_name else ""
        if event_name not in _TIMESERIES_GATE_EVENT_NAMES:
            continue
        raw_time = event.get("time_s")
        try:
            time_s = float(raw_time)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        key = (event_name, round(time_s, 6))
        if key in seen:
            continue
        seen.add(key)
        short_label = _EVENT_DISPLAY_NAMES.get(event_name, event_name.replace("_", " "))
        raw_label = event.get("label")
        if isinstance(raw_label, str) and raw_label.strip():
            label = raw_label.strip()
        else:
            label = short_label
        out.append((event_name, time_s, label))
    out.sort(key=lambda item: item[1])
    return out


def _draw_timeseries_event_lines(
    ax,
    *,
    events: list[dict[str, float | str | None]] | None,
) -> None:
    gate_events = _sorted_gate_events(events)
    if not gate_events:
        return
    top_y = 0.98
    for idx, (event_name, time_s, label) in enumerate(gate_events):
        color = _EVENT_COLORS.get(event_name, "#444444")
        ax.axvline(
            time_s,
            color=color,
            linewidth=1.0,
            linestyle=(0, (4, 4)),
            alpha=0.72,
            zorder=0,
        )
        ax.text(
            time_s,
            top_y - (0.08 * (idx % 2)),
            label,
            rotation=90,
            rotation_mode="anchor",
            transform=ax.get_xaxis_transform(),
            fontsize=7,
            color=color,
            ha="right",
            va="top",
            bbox={
                "boxstyle": "round,pad=0.14",
                "facecolor": "#ffffff",
                "edgecolor": "none",
                "alpha": 0.72,
            },
            zorder=5,
        )


def _draw_spatial_legend(ax, *, legend_ax=None) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        if legend_ax is not None:
            legend_ax.axis("off")
        return
    if legend_ax is None:
        ax.legend(handles, labels, loc="upper right", fontsize=8)
        return
    legend_ax.axis("off")
    legend_ax.legend(
        handles,
        labels,
        loc="center left",
        ncol=min(3, len(handles)),
        fontsize=8,
        frameon=False,
        handlelength=1.8,
        columnspacing=1.2,
    )


def _draw_target(ax, *, target: dict[str, float | str | None] | None) -> None:
    if target is None:
        return
    try:
        target_x = float(target.get("x", 0.0) or 0.0)
        target_y = float(target.get("y", 0.0) or 0.0)
    except (TypeError, ValueError):
        target_x = 0.0
        target_y = 0.0
    try:
        target_size = abs(float(target.get("size", 0.0) or 0.0))
    except (TypeError, ValueError):
        target_size = 0.0
    target_label_raw = target.get("label", "target")
    target_label = str(target_label_raw) if target_label_raw else "target"
    half_width = max(18.0, target_size * 0.5)
    left_x = target_x - half_width
    right_x = target_x + half_width
    cap_height = max(10.0, half_width * 0.18)
    target_color = "#2ecc71"

    ax.plot(
        [left_x, right_x],
        [target_y, target_y],
        color="#ffffff",
        linewidth=8.4,
        solid_capstyle="round",
        alpha=0.98,
        zorder=7,
    )
    ax.plot(
        [left_x, right_x],
        [target_y, target_y],
        color=target_color,
        linewidth=4.8,
        solid_capstyle="round",
        alpha=1.0,
        zorder=8,
        label=target_label,
    )
    for x in (left_x, right_x):
        ax.plot(
            [x, x],
            [target_y - cap_height, target_y + cap_height],
            color="#ffffff",
            linewidth=5.4,
            solid_capstyle="round",
            alpha=0.98,
            zorder=7,
        )
        ax.plot(
            [x, x],
            [target_y - cap_height, target_y + cap_height],
            color=target_color,
            linewidth=2.8,
            solid_capstyle="round",
            alpha=1.0,
            zorder=8,
        )


def _spatial_limits_with_target(
    ctx: _PlotContext,
    *,
    target: dict[str, float | str | None] | None,
    extra_points: list[tuple[float, float]] | None = None,
    overlay_curves: list[dict[str, Any] | None] | None = None,
) -> tuple[float, float, float, float]:
    min_x = float(ctx.min_x)
    max_x = float(ctx.max_x)
    lower_y = float(ctx.lower_y)
    upper_y = float(ctx.upper_y)
    if target is not None:
        try:
            target_x = float(target.get("x", 0.0) or 0.0)
            target_y = float(target.get("y", 0.0) or 0.0)
            target_size = abs(float(target.get("size", 0.0) or 0.0))
        except (TypeError, ValueError):
            target_x = 0.0
            target_y = 0.0
            target_size = 0.0

        half_width = max(18.0, 0.5 * target_size)
        cap_height = max(10.0, half_width * 0.18)
        x_pad = max(12.0, 0.20 * half_width)
        y_pad = max(12.0, 0.35 * cap_height)
        min_x = min(min_x, target_x - half_width - x_pad)
        max_x = max(max_x, target_x + half_width + x_pad)
        lower_y = min(lower_y, target_y - cap_height - y_pad)
        upper_y = max(upper_y, target_y + cap_height + y_pad)
    if overlay_curves:
        curve_x_pad = max(8.0, 0.02 * max(max_x - min_x, 1.0))
        curve_y_pad = max(8.0, 0.03 * max(upper_y - lower_y, 1.0))
        for curve in overlay_curves:
            if not isinstance(curve, dict):
                continue
            xs = list(curve.get("xs") or [])
            ys = list(curve.get("ys") or [])
            for point_x, point_y in zip(xs, ys, strict=False):
                try:
                    px = float(point_x)
                    py = float(point_y)
                except (TypeError, ValueError):
                    continue
                min_x = min(min_x, px - curve_x_pad)
                max_x = max(max_x, px + curve_x_pad)
                lower_y = min(lower_y, py - curve_y_pad)
                upper_y = max(upper_y, py + curve_y_pad)
    if extra_points:
        point_x_pad = max(8.0, 0.02 * max(max_x - min_x, 1.0))
        point_y_pad = max(8.0, 0.03 * max(upper_y - lower_y, 1.0))
        for point_x, point_y in extra_points:
            min_x = min(min_x, float(point_x) - point_x_pad)
            max_x = max(max_x, float(point_x) + point_x_pad)
            lower_y = min(lower_y, float(point_y) - point_y_pad)
            upper_y = max(upper_y, float(point_y) + point_y_pad)
    return min_x, max_x, lower_y, upper_y


def _curve_apex_point(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    if not xs or not ys:
        return None
    count = min(len(xs), len(ys))
    if count < 3:
        return None
    apex_idx = max(range(count), key=lambda idx: float(ys[idx]))
    if apex_idx <= 0 or apex_idx >= count - 1:
        return None
    apex_y = float(ys[apex_idx])
    rise_eps = 1e-6
    has_climb = any((apex_y - float(y_val)) > rise_eps for y_val in ys[:apex_idx])
    has_descent = any(
        (apex_y - float(y_val)) > rise_eps for y_val in ys[apex_idx + 1 : count]
    )
    if not (has_climb and has_descent):
        return None
    return float(xs[apex_idx]), apex_y


def _projected_apex_point(
    ctx: _PlotContext,
    *,
    target: dict[str, float | str | None] | None,
    events: list[dict[str, float | str | None]] | None = None,
    gravity_mag: float = GRAVITY_MAG,
) -> tuple[float, float] | None:
    if target is None:
        return None
    state_x = float(ctx.xs[-1]) if ctx.xs else 0.0
    state_y = float(ctx.ys[-1]) if ctx.ys else 0.0
    state_vx = float(ctx.vxs[-1]) if ctx.vxs else 0.0
    state_vy = float(ctx.vys[-1]) if ctx.vys else 0.0
    for event in reversed(list(events or [])):
        try:
            event_x = float(event.get("x"))  # type: ignore[arg-type]
            event_y = float(event.get("y"))  # type: ignore[arg-type]
            event_vx = float(event.get("vx"))  # type: ignore[arg-type]
            event_vy = float(event.get("vy_up"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        state_x = event_x
        state_y = event_y
        state_vx = event_vx
        state_vy = event_vy
        break
    apex = ballistic_apex_from_state(
        x=state_x,
        y=state_y,
        vx=state_vx,
        vy_up=state_vy,
        gravity_mag=gravity_mag,
    )
    if apex.t_apex <= 1e-6 or apex.x_apex is None:
        return None
    return float(apex.x_apex), float(apex.y_apex)


def _draw_apex_marker(
    ax,
    *,
    point: tuple[float, float] | None,
    label: str,
    color: str,
) -> None:
    if point is None:
        return
    apex_x, apex_y = point
    ax.scatter(
        [apex_x],
        [apex_y],
        s=42.0,
        marker="^",
        facecolors="#ffffff",
        edgecolors=color,
        linewidths=1.1,
        alpha=0.98,
        zorder=8,
        label=label,
    )
    ax.annotate(
        label,
        xy=(apex_x, apex_y),
        xytext=(5, 7),
        textcoords="offset points",
        fontsize=7,
        color=color,
        zorder=9,
    )


def _vector_sample_indices(sample_times: list[float]) -> list[int]:
    if len(sample_times) <= 1:
        return [0]
    total_t = max(0.0, float(sample_times[-1] - sample_times[0]))
    interval_s = max(0.35, total_t / 22.0)
    picked: list[int] = []
    next_t = float(sample_times[0])
    for idx, t_val in enumerate(sample_times):
        t = float(t_val)
        if not picked or t >= next_t - 1e-9:
            picked.append(idx)
            next_t = t + interval_s
    if picked[-1] != len(sample_times) - 1:
        picked.append(len(sample_times) - 1)
    return picked


def _projected_intercept_from_state(
    *,
    x: float,
    y: float,
    vx: float,
    vy_up: float,
    target_x: float,
    target_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> _ProjectedIntercept:
    projection = estimate_target_y_projection(
        dx=float(target_x) - float(x),
        dy=float(target_y) - float(y),
        vx=float(vx),
        vy_up=float(vy_up),
        x=float(x),
        y=float(y),
        min_t_fall=0.0,
        gravity_mag=gravity_mag,
    )
    apex = ballistic_apex_from_state(
        x=float(x),
        y=float(y),
        vx=float(vx),
        vy_up=float(vy_up),
        gravity_mag=gravity_mag,
    )
    apex_x = float(
        apex.x_apex
        if apex.x_apex is not None
        else (float(x) + (float(vx) * float(apex.t_apex)))
    )
    apex_y = float(apex.y_apex)
    if not projection.has_target_y_solution:
        return _ProjectedIntercept(
            end_x=apex_x,
            end_y=apex_y,
            miss_dx=float(target_x) - apex_x,
            t_end=max(0.0, float(apex.t_apex)),
            has_target_y_solution=False,
        )
    end_x = float(
        projection.impact_x
        if projection.impact_x is not None
        else (float(x) + (float(vx) * float(projection.t_fall)))
    )
    return _ProjectedIntercept(
        end_x=end_x,
        end_y=float(target_y),
        miss_dx=float(projection.projected_dx),
        t_end=float(projection.t_fall),
        has_target_y_solution=True,
    )


def _ballistic_curve_from_state(
    *,
    x: float,
    y: float,
    vx: float,
    vy_up: float,
    target_x: float,
    target_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> tuple[list[float], list[float], bool]:
    import numpy as np

    intercept = _projected_intercept_from_state(
        x=x,
        y=y,
        vx=vx,
        vy_up=vy_up,
        target_x=target_x,
        target_y=target_y,
        gravity_mag=gravity_mag,
    )
    point_count = max(18, min(56, int(12 + (intercept.t_end * 10.0))))
    t_vals = np.linspace(0.0, max(0.0, intercept.t_end), point_count)
    xs = [float(x + (vx * t_val)) for t_val in t_vals]
    ys = [
        float(y + (vy_up * t_val) - (0.5 * gravity_mag * t_val * t_val))
        for t_val in t_vals
    ]
    if xs:
        xs[-1] = intercept.end_x
        ys[-1] = intercept.end_y
    return xs, ys, intercept.has_target_y_solution


def _vx_corrected_ballistic_reference_curve(
    *,
    start_x: float,
    start_y: float,
    vx: float,
    vy_up: float,
    target_x: float,
    target_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> tuple[list[float], list[float]] | None:
    import numpy as np

    intercept = _projected_intercept_from_state(
        x=start_x,
        y=start_y,
        vx=vx,
        vy_up=vy_up,
        target_x=target_x,
        target_y=target_y,
        gravity_mag=gravity_mag,
    )
    if not intercept.has_target_y_solution or intercept.t_end <= 1e-6:
        return None

    flight_t = float(intercept.t_end)
    point_count = max(24, min(80, int(16 + (flight_t * 10.0))))
    t_vals = np.linspace(0.0, flight_t, point_count)
    corrected_vx = (float(target_x) - float(start_x)) / flight_t
    xs: list[float] = []
    ys: list[float] = []
    for t_val in t_vals:
        raw_x = float(start_x + (corrected_vx * t_val))
        raw_y = float(start_y + (vy_up * t_val) - (0.5 * gravity_mag * t_val * t_val))
        xs.append(raw_x)
        ys.append(raw_y)
    if xs:
        xs[-1] = float(target_x)
        ys[-1] = float(target_y)
    return xs, ys


def _idealized_reference_curve(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    apex_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> tuple[list[float], list[float]] | None:
    import numpy as np

    g = max(1e-6, abs(float(gravity_mag)))
    solution = _idealized_reference_kinematics(
        start_x=start_x,
        start_y=start_y,
        target_x=target_x,
        target_y=target_y,
        apex_y=apex_y,
        gravity_mag=gravity_mag,
    )
    if solution is None:
        return None

    point_count = max(24, min(80, int(16 + (solution.flight_t * 10.0))))
    t_vals = np.linspace(0.0, solution.flight_t, point_count)
    xs = [float(start_x + (solution.vx * t_val)) for t_val in t_vals]
    ys = [
        float(start_y + (solution.vy_up * t_val) - (0.5 * g * t_val * t_val))
        for t_val in t_vals
    ]
    if xs:
        xs[-1] = float(target_x)
        ys[-1] = float(target_y)
    return xs, ys


def _idealized_reference_kinematics(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    apex_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> _IdealizedReferenceKinematics | None:
    g = max(1e-6, abs(float(gravity_mag)))
    peak_y = max(float(start_y), float(apex_y))
    peak_over_start = peak_y - float(start_y)
    vy_up = math.sqrt(max(0.0, 2.0 * g * peak_over_start))
    t_cross, has_solution = time_to_target_y_crossing(
        dy=float(target_y) - float(start_y),
        vy_up=vy_up,
        gravity_mag=g,
        prefer_descending=True,
    )
    if not has_solution or t_cross is None or t_cross <= 1e-6:
        return None
    flight_t = float(t_cross)
    vx = (float(target_x) - float(start_x)) / flight_t
    return _IdealizedReferenceKinematics(flight_t=flight_t, vx=vx, vy_up=vy_up)


def _idealized_reference_impact_angle_deg(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    apex_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> float | None:
    solution = _idealized_reference_kinematics(
        start_x=start_x,
        start_y=start_y,
        target_x=target_x,
        target_y=target_y,
        apex_y=apex_y,
        gravity_mag=gravity_mag,
    )
    if solution is None:
        return None
    g = max(1e-6, abs(float(gravity_mag)))
    vy_target = float(solution.vy_up) - (g * float(solution.flight_t))
    descent_speed = max(0.0, -vy_target)
    return math.degrees(math.atan2(descent_speed, abs(float(solution.vx))))


def _idealized_reference_exit_angle_deg(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    apex_y: float,
    gravity_mag: float = GRAVITY_MAG,
) -> float | None:
    solution = _idealized_reference_kinematics(
        start_x=start_x,
        start_y=start_y,
        target_x=target_x,
        target_y=target_y,
        apex_y=apex_y,
        gravity_mag=gravity_mag,
    )
    if solution is None:
        return None
    ascent_speed = max(0.0, float(solution.vy_up))
    return math.degrees(math.atan2(ascent_speed, abs(float(solution.vx))))


def _idealized_reference_apex_y(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    min_descent_angle_deg: float = 45.0,
    min_exit_angle_deg: float = 45.0,
    downhill_policy: Literal["descent_angle", "exit_angle"] = "descent_angle",
    gravity_mag: float = GRAVITY_MAG,
) -> float:
    start_x = float(start_x)
    start_y = float(start_y)
    target_x = float(target_x)
    target_y = float(target_y)
    min_descent_angle_deg = float(min_descent_angle_deg)
    min_exit_angle_deg = float(min_exit_angle_deg)
    dx = target_x - start_x
    dy = target_y - start_y
    if target_y > start_y:
        base_peak = max(start_y, target_y + 1.0)
    else:
        base_peak = start_y
    if abs(dx) <= 1e-6:
        return base_peak

    def meets_angle_floor(peak_y: float) -> bool:
        if target_y < start_y and downhill_policy == "exit_angle":
            exit_angle_deg = _idealized_reference_exit_angle_deg(
                start_x=start_x,
                start_y=start_y,
                target_x=target_x,
                target_y=target_y,
                apex_y=peak_y,
                gravity_mag=gravity_mag,
            )
            return exit_angle_deg is not None and exit_angle_deg >= min_exit_angle_deg

        impact_angle_deg = _idealized_reference_impact_angle_deg(
            start_x=start_x,
            start_y=start_y,
            target_x=target_x,
            target_y=target_y,
            apex_y=peak_y,
            gravity_mag=gravity_mag,
        )
        return (
            impact_angle_deg is not None and impact_angle_deg >= min_descent_angle_deg
        )

    if meets_angle_floor(base_peak):
        return base_peak

    low_peak = base_peak
    growth = max(16.0, 0.25 * max(abs(dx), abs(dy), 1.0))
    high_peak: float | None = None
    candidate_peak = base_peak
    for _ in range(16):
        candidate_peak = candidate_peak + growth
        if meets_angle_floor(candidate_peak):
            high_peak = candidate_peak
            break
        low_peak = candidate_peak
        growth *= 2.0
    if high_peak is None:
        return candidate_peak

    for _ in range(32):
        mid_peak = 0.5 * (low_peak + high_peak)
        if meets_angle_floor(mid_peak):
            high_peak = mid_peak
        else:
            low_peak = mid_peak
    return high_peak


def _find_event(events, *, name: str) -> dict[str, float | str | None] | None:
    for event in events or []:
        if str(event.get("name") or "").strip().lower() == name:
            return event
    return None


def _draw_spatial_common(
    ax,
    *,
    ctx: _PlotContext,
    events,
    target,
    extra_points: list[tuple[float, float]] | None = None,
    overlay_curves: list[dict[str, Any] | None] | None = None,
    title: str,
    legend_ax=None,
    show_xlabel: bool = True,
) -> None:
    _draw_events(ax, events=events)
    _draw_target(ax, target=target)
    min_x, max_x, lower_y, upper_y = _spatial_limits_with_target(
        ctx,
        target=target,
        extra_points=extra_points,
        overlay_curves=overlay_curves,
    )
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(lower_y, upper_y)
    ax.set_aspect("equal", adjustable="box")
    span_x = max_x - min_x
    span_y = upper_y - lower_y
    ax.set_anchor("C" if _is_tall_spatial(span_x, span_y) else "W")
    ax.set_xlabel("x (world units)" if show_xlabel else "")
    ax.set_ylabel("y (world units)")
    ax.set_title(title, pad=10.0)
    ax.grid(True, linestyle=":", alpha=0.3)
    _draw_spatial_legend(ax, legend_ax=legend_ax)


def _draw_spatial_panel(
    fig,
    ax,
    *,
    ctx: _PlotContext,
    events,
    target,
    cax=None,
    legend_ax=None,
    cbar_orientation: Literal["vertical", "horizontal"] = "vertical",
    color_mode: Literal["speed", "thrust"],
    title: str,
    show_xlabel: bool = True,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    ax.plot(
        ctx.terrain_xs,
        ctx.terrain_ys,
        color="#444444",
        linewidth=1.0,
        alpha=0.85,
        label="terrain",
    )
    if color_mode == "thrust":
        vals = ctx.thrust_seg_vals
        cmap = "Blues"
        vmin, vmax = 0.0, 1.0
        cbar_label = "thrust (0..1)"
    else:
        vals = ctx.speed_seg_vals
        vmax = float(vals.max() if vals.size > 0 else 1.0)
        if vmax <= 0.0:
            vmax = 1.0
        vmin = 0.0
        cmap = "RdYlGn_r"
        cbar_label = "speed (world units/s)"
    lc = LineCollection(
        ctx.segments, cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax)
    )
    lc.set_array(vals)
    lc.set_linewidth(2.0)
    ax.add_collection(lc)
    cbar = (
        fig.colorbar(lc, cax=cax, orientation=cbar_orientation)
        if cax is not None
        else fig.colorbar(lc, ax=ax, pad=0.01)
    )
    cbar.set_label(cbar_label)
    actual_apex = _curve_apex_point(ctx.xs, ctx.ys)
    projected_apex = _projected_apex_point(ctx, target=target, events=events)
    _draw_apex_marker(ax, point=actual_apex, label="apex", color="#1b263b")
    _draw_apex_marker(ax, point=projected_apex, label="projected apex", color="#cc0000")
    extra_points = [
        point for point in (actual_apex, projected_apex) if point is not None
    ]

    _draw_spatial_common(
        ax,
        ctx=ctx,
        events=events,
        target=target,
        extra_points=extra_points or None,
        title=title,
        legend_ax=legend_ax,
        show_xlabel=show_xlabel,
    )


def _draw_vector_spatial_panel(
    fig,
    ax,
    *,
    ctx: _PlotContext,
    events,
    target,
    cax=None,
    legend_ax=None,
    cbar_orientation: Literal["vertical", "horizontal"] = "vertical",
    title: str,
    show_xlabel: bool = True,
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    ax.plot(
        ctx.terrain_xs,
        ctx.terrain_ys,
        color="#444444",
        linewidth=1.0,
        alpha=0.85,
        label="terrain",
    )
    ax.plot(
        ctx.xs, ctx.ys, color="#777777", linewidth=1.25, alpha=0.42, label="trajectory"
    )

    vector_len = 0.038 * max(ctx.span_x, ctx.span_y, 1.0)
    vx_dir = np.sin(ctx.angle_arr)
    vy_dir = np.cos(ctx.angle_arr)
    sampled = np.array(_vector_sample_indices(ctx.sample_times), dtype=int)
    sampled_thrust = ctx.thrust_arr[sampled]
    sampled_x = ctx.points[sampled, 0]
    sampled_y = ctx.points[sampled, 1]

    active_mask = sampled_thrust > 0.01
    if np.any(active_mask):
        idx = sampled[active_mask]
        q = ax.quiver(
            ctx.points[idx, 0],
            ctx.points[idx, 1],
            vx_dir[idx] * vector_len * ctx.thrust_arr[idx],
            vy_dir[idx] * vector_len * ctx.thrust_arr[idx],
            ctx.thrust_arr[idx],
            cmap="Blues",
            norm=plt.Normalize(vmin=0.0, vmax=1.0),
            angles="xy",
            scale_units="xy",
            scale=1.0,
            width=0.0024,
            headwidth=5.2,
            headlength=6.6,
            headaxislength=5.5,
            alpha=0.95,
            zorder=5,
        )
        if cax is not None:
            cbar = fig.colorbar(q, cax=cax, orientation=cbar_orientation)
        else:
            cbar = fig.colorbar(q, ax=ax, pad=0.01)
        cbar.set_label("thrust (0..1)")
    elif cax is not None:
        cax.axis("off")

    zero_mask = ~active_mask
    if np.any(zero_mask):
        ax.scatter(
            sampled_x[zero_mask],
            sampled_y[zero_mask],
            s=14.0,
            marker="o",
            facecolors="#f8fbff",
            edgecolors="#4f79a7",
            linewidths=0.8,
            alpha=0.95,
            zorder=6,
            label="zero thrust",
        )
    actual_apex = _curve_apex_point(ctx.xs, ctx.ys)
    projected_apex = _projected_apex_point(ctx, target=target, events=events)
    _draw_apex_marker(ax, point=actual_apex, label="apex", color="#1b263b")
    _draw_apex_marker(ax, point=projected_apex, label="projected apex", color="#cc0000")
    extra_points = [
        point for point in (actual_apex, projected_apex) if point is not None
    ]

    _draw_spatial_common(
        ax,
        ctx=ctx,
        events=events,
        target=target,
        extra_points=extra_points or None,
        title=title,
        legend_ax=legend_ax,
        show_xlabel=show_xlabel,
    )


def _draw_trajectory_comparison_spatial_panel(
    fig,
    ax,
    *,
    ctx: _PlotContext,
    events,
    target,
    cax=None,
    legend_ax=None,
    cbar_orientation: Literal["vertical", "horizontal"] = "vertical",
    title: str,
    show_xlabel: bool = True,
) -> None:
    import matplotlib.patheffects as pe

    ax.plot(
        ctx.terrain_xs,
        ctx.terrain_ys,
        color="#444444",
        linewidth=1.0,
        alpha=0.85,
        label="terrain",
    )
    actual_line = ax.plot(
        ctx.xs,
        ctx.ys,
        color="#1b263b",
        linewidth=3.2,
        alpha=0.99,
        zorder=6,
        label="actual trajectory",
    )[0]
    actual_line.set_path_effects(
        [pe.Stroke(linewidth=6.0, foreground="#ffffff"), pe.Normal()]
    )
    ax.scatter(
        [ctx.xs[0], ctx.xs[-1]],
        [ctx.ys[0], ctx.ys[-1]],
        s=(26.0, 34.0),
        marker="o",
        facecolors=("#ffffff", "#1b263b"),
        edgecolors="#1b263b",
        linewidths=1.1,
        alpha=0.98,
        zorder=7,
    )
    overlay_points: list[tuple[float, float]] = []
    actual_apex = _curve_apex_point(ctx.xs, ctx.ys)
    if actual_apex is not None:
        overlay_points.append(actual_apex)
    _draw_apex_marker(ax, point=actual_apex, label="actual apex", color="#1b263b")

    boost_cutoff_event = _find_event(events, name="boost_cutoff")
    overlay_curves: list[dict[str, Any]] = []
    if target is None:
        if cax is not None:
            cax.axis("off")
        _draw_spatial_common(
            ax,
            ctx=ctx,
            events=events,
            target=target,
            extra_points=overlay_points or None,
            overlay_curves=overlay_curves or None,
            title=title,
            legend_ax=legend_ax,
            show_xlabel=show_xlabel,
        )
        return
    try:
        target_x = float(target.get("x", 0.0) or 0.0)
        target_y = float(target.get("y", 0.0) or 0.0)
    except (TypeError, ValueError):
        target_x = 0.0
        target_y = 0.0
    projected_apex = _projected_apex_point(ctx, target=target, events=events)
    if projected_apex is not None:
        overlay_points.append(projected_apex)
    _draw_apex_marker(ax, point=projected_apex, label="projected apex", color="#cc0000")

    reference_apex_y = _idealized_reference_apex_y(
        start_x=float(ctx.xs[0]),
        start_y=float(ctx.ys[0]),
        target_x=target_x,
        target_y=target_y,
    )
    reference_curve = _idealized_reference_curve(
        start_x=float(ctx.xs[0]),
        start_y=float(ctx.ys[0]),
        target_x=target_x,
        target_y=target_y,
        apex_y=reference_apex_y,
    )
    if reference_curve is not None:
        ref_xs, ref_ys = reference_curve
        ref_apex = _curve_apex_point(ref_xs, ref_ys)
        if ref_apex is not None:
            overlay_points.append(ref_apex)
        overlay_curves.append(
            {
                "xs": [float(value) for value in ref_xs],
                "ys": [float(value) for value in ref_ys],
            }
        )
        ref_line = ax.plot(
            ref_xs,
            ref_ys,
            color="#00ff00",
            linewidth=2.3,
            linestyle=(0, (8, 4)),
            alpha=0.98,
            zorder=5,
            label="idealized reference",
        )[0]
        ref_line.set_path_effects(
            [pe.Stroke(linewidth=4.2, foreground="#111111"), pe.Normal()]
        )
        _draw_apex_marker(ax, point=ref_apex, label="reference apex", color="#00aa00")

    if boost_cutoff_event is not None:
        event_x = float(boost_cutoff_event.get("x", 0.0) or 0.0)
        event_y = float(boost_cutoff_event.get("y", 0.0) or 0.0)
        event_vx = boost_cutoff_event.get("vx")
        event_vy_up = boost_cutoff_event.get("vy_up")
        if event_vx is not None and event_vy_up is not None:
            boost_curve_xs, boost_curve_ys, has_target_y_solution = (
                _ballistic_curve_from_state(
                    x=event_x,
                    y=event_y,
                    vx=float(event_vx),
                    vy_up=float(event_vy_up),
                    target_x=target_x,
                    target_y=target_y,
                )
            )
            if has_target_y_solution:
                boost_apex = _curve_apex_point(boost_curve_xs, boost_curve_ys)
                if boost_apex is not None:
                    overlay_points.append(boost_apex)
                overlay_curves.append(
                    {
                        "xs": [float(value) for value in boost_curve_xs],
                        "ys": [float(value) for value in boost_curve_ys],
                    }
                )
                boost_line = ax.plot(
                    boost_curve_xs,
                    boost_curve_ys,
                    color="#ff0000",
                    linewidth=2.4,
                    linestyle=(0, (2.2, 2.0)),
                    alpha=0.98,
                    zorder=6,
                    label="boost cutoff ballistic",
                )[0]
                boost_line.set_path_effects(
                    [pe.Stroke(linewidth=4.4, foreground="#111111"), pe.Normal()]
                )
                _draw_apex_marker(
                    ax, point=boost_apex, label="boost ballistic apex", color="#cc0000"
                )
                ax.scatter(
                    [boost_curve_xs[0], boost_curve_xs[-1]],
                    [boost_curve_ys[0], boost_curve_ys[-1]],
                    s=22.0,
                    marker="D",
                    facecolors="#ffffff",
                    edgecolors="#ff0000",
                    linewidths=1.0,
                    alpha=0.98,
                    zorder=7,
                )

    if cax is not None:
        cax.axis("off")

    _draw_spatial_common(
        ax,
        ctx=ctx,
        events=events,
        target=target,
        extra_points=overlay_points or None,
        overlay_curves=overlay_curves or None,
        title=title,
        legend_ax=legend_ax,
        show_xlabel=show_xlabel,
    )


def _draw_speed_thrust_timeseries_panel(
    ax,
    *,
    ctx: _PlotContext,
    events,
    title: str,
    show_xlabel: bool,
) -> None:
    import numpy as np

    t = np.array(ctx.sample_times, dtype=float)
    speed_line = ax.plot(t, ctx.speeds, color="#d62728", linewidth=1.2, label="speed")[
        0
    ]
    ax.set_ylabel("speed")
    max_speed = max(ctx.speeds) if ctx.speeds else 1.0
    ax.set_ylim(0.0, max(1.0, max_speed * 1.14))
    ax.grid(True, linestyle=":", alpha=0.25)

    ax_thrust = ax.twinx()
    thrust_line = ax_thrust.plot(
        t, ctx.thrusts, color="#1f77b4", linewidth=1.15, alpha=0.92, label="thrust"
    )[0]
    ax_thrust.set_ylabel("thrust")
    max_thrust = max(ctx.thrusts) if ctx.thrusts else 1.0
    ax_thrust.set_ylim(0.0, max(1.0, max_thrust * 1.05))
    _draw_timeseries_event_lines(ax, events=events)
    ax.set_xlabel("time (s)" if show_xlabel else "")
    ax.set_title(title)
    ax.legend(
        [speed_line, thrust_line],
        ["speed", "thrust"],
        loc="upper right",
        fontsize=8,
    )
    ax.tick_params(labelbottom=True)


def _ballistic_projection_series(
    *,
    ctx: _PlotContext,
    target: dict[str, float | str | None] | None,
    gravity_mag: float = GRAVITY_MAG,
) -> tuple[list[float], list[float]]:
    target_x = float(target.get("x", 0.0) or 0.0) if target else 0.0
    target_y = float(target.get("y", 0.0) or 0.0) if target else 0.0
    g = max(1e-6, abs(float(gravity_mag)))
    apex_over_target: list[float] = []
    projected_dx: list[float] = []
    for x, y, vx, vy_up in zip(ctx.xs, ctx.ys, ctx.vxs, ctx.vys, strict=True):
        t_apex = max(0.0, float(vy_up) / g)
        apex_y = float(y) + (float(vy_up) * t_apex) - (0.5 * g * t_apex * t_apex)
        apex_over_target.append(apex_y - target_y)
        intercept = _projected_intercept_from_state(
            x=float(x),
            y=float(y),
            vx=float(vx),
            vy_up=float(vy_up),
            target_x=target_x,
            target_y=target_y,
            gravity_mag=g,
        )
        projected_dx.append(float(intercept.miss_dx))
    return apex_over_target, projected_dx


def _draw_ballistic_projection_timeseries_panel(
    ax,
    *,
    ctx: _PlotContext,
    events,
    target: dict[str, float | str | None] | None,
    title: str,
    show_xlabel: bool,
) -> None:
    import numpy as np

    t = np.array(ctx.sample_times, dtype=float)
    apex_over_target, projected_dx = _ballistic_projection_series(
        ctx=ctx, target=target
    )
    apex_arr = np.array(apex_over_target, dtype=float)
    dx_arr = np.array(projected_dx, dtype=float)
    ax.plot(
        t,
        apex_arr,
        color="#2ca02c",
        linewidth=1.25,
        label="engine-off apex_y - target_y",
    )
    ax.plot(
        t,
        dx_arr,
        color="#d62728",
        linewidth=1.2,
        label="engine-off target_x - projected_x",
    )
    ax.axhline(0.0, color="#777777", linewidth=0.8, linestyle=":")
    y_min = min(float(apex_arr.min(initial=0.0)), float(dx_arr.min(initial=0.0)), 0.0)
    y_max = max(float(apex_arr.max(initial=0.0)), float(dx_arr.max(initial=0.0)), 0.0)
    span = max(1.0, y_max - y_min)
    ax.set_ylim(y_min - (0.04 * span), y_max + (0.18 * span))
    _draw_timeseries_event_lines(ax, events=events)
    ax.set_xlabel("time (s)" if show_xlabel else "")
    ax.set_ylabel("target-relative")
    ax.set_title(title)
    ax.grid(True, linestyle=":", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    ax.tick_params(labelbottom=True)


def _draw_hv_timeseries_panel(
    ax,
    *,
    ctx: _PlotContext,
    events,
    title: str,
    show_xlabel: bool,
) -> None:
    import numpy as np

    t = np.array(ctx.sample_times, dtype=float)
    vx = np.array(ctx.vxs, dtype=float)
    vy = np.array(ctx.vys, dtype=float)
    ax.plot(t, vx, color="#2ca02c", linewidth=1.1, label="vx")
    ax.plot(t, vy, color="#9467bd", linewidth=1.1, label="vy_up")
    ax.axhline(0.0, color="#777777", linewidth=0.8, linestyle=":")
    y_min = min(float(vx.min(initial=0.0)), float(vy.min(initial=0.0)), 0.0)
    y_max = max(float(vx.max(initial=0.0)), float(vy.max(initial=0.0)), 0.0)
    span = max(1.0, y_max - y_min)
    ax.set_ylim(y_min - (0.04 * span), y_max + (0.16 * span))
    _draw_timeseries_event_lines(ax, events=events)
    ax.set_xlabel("time (s)" if show_xlabel else "")
    ax.set_ylabel("velocity")
    ax.set_title(title)
    ax.grid(True, linestyle=":", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    ax.tick_params(labelbottom=True)


def _draw_thrust_component_timeseries_panel(
    ax,
    *,
    ctx: _PlotContext,
    events,
    title: str,
    show_xlabel: bool,
) -> None:
    import numpy as np

    t = np.array(ctx.sample_times, dtype=float)
    thrust = np.array(ctx.thrusts, dtype=float)
    thrust_x = thrust * np.sin(ctx.angle_arr)
    thrust_y = thrust * np.cos(ctx.angle_arr)
    ax.plot(t, thrust_x, color="#1f77b4", linewidth=1.1, label="thrust_x")
    ax.plot(t, thrust_y, color="#ff7f0e", linewidth=1.1, label="thrust_y")
    ax.axhline(0.0, color="#777777", linewidth=0.8, linestyle=":")
    y_min = min(float(thrust_x.min(initial=0.0)), float(thrust_y.min(initial=0.0)), 0.0)
    y_max = max(float(thrust_x.max(initial=0.0)), float(thrust_y.max(initial=0.0)), 0.0)
    span = max(1.0, y_max - y_min)
    ax.set_ylim(y_min - (0.04 * span), y_max + (0.16 * span))
    _draw_timeseries_event_lines(ax, events=events)
    ax.set_xlabel("time (s)" if show_xlabel else "")
    ax.set_ylabel("thrust component")
    ax.set_title(title)
    ax.grid(True, linestyle=":", alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    ax.tick_params(labelbottom=True)


def _save_figure(fig, out_file: Path, *, max_side_px: int, base_dpi: int = 150) -> str:
    fig_w, fig_h = fig.get_size_inches()
    dpi = _resolve_dpi(fig_w, fig_h, base_dpi=base_dpi, max_side_px=max_side_px)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=dpi)
    import matplotlib.pyplot as plt

    plt.close(fig)
    return str(out_file)


def _create_spatial_axes(
    fig,
    spec,
    *,
    colorbar_position: Literal["right", "bottom"],
    sharex=None,
    sharey=None,
) -> tuple[Any, Any, Any]:
    if colorbar_position == "bottom":
        sub = spec.subgridspec(3, 1, height_ratios=(0.16, 1.0, 0.10), hspace=0.05)
        legend_ax = fig.add_subplot(sub[0, 0])
        ax = fig.add_subplot(sub[1, 0], sharex=sharex, sharey=sharey)
        cax = fig.add_subplot(sub[2, 0])
    else:
        sub = spec.subgridspec(
            2,
            2,
            height_ratios=(0.18, 1.0),
            width_ratios=(1.0, 0.055),
            hspace=0.04,
            wspace=0.08,
        )
        legend_ax = fig.add_subplot(sub[0, :])
        ax = fig.add_subplot(sub[1, 0], sharex=sharex, sharey=sharey)
        cax = fig.add_subplot(sub[1, 1])
    legend_ax.axis("off")
    return ax, cax, legend_ax


def _render_combined_plot(
    *,
    ctx: _PlotContext,
    mode: Literal["speed", "thrust", "all"],
    out_file: Path,
    max_side_px: int,
    events: list[dict[str, float | str | None]] | None,
    target: dict[str, float | str | None] | None,
) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if mode == "all":
        arrangement = _combined_spatial_arrangement(ctx.span_x, ctx.span_y)
        fig_w, fig_h = _compute_figure_size(
            ctx.span_x,
            ctx.span_y,
            layout="all",
            arrangement=arrangement,
        )
        fig = plt.figure(figsize=(fig_w, fig_h))
        if arrangement == "columns":
            grid = fig.add_gridspec(
                6,
                2,
                height_ratios=(4.2, 4.2, 1.35, 1.35, 1.35, 1.35),
                hspace=0.22,
                wspace=0.06,
            )
            ax_compare, cax_compare, lax_compare = _create_spatial_axes(
                fig,
                grid[0, 0],
                colorbar_position="bottom",
            )
            ax_speed, cax_speed, lax_speed = _create_spatial_axes(
                fig,
                grid[0, 1],
                colorbar_position="bottom",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_thrust, cax_thrust, lax_thrust = _create_spatial_axes(
                fig,
                grid[1, 0],
                colorbar_position="bottom",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_vectors, cax_vectors, lax_vectors = _create_spatial_axes(
                fig,
                grid[1, 1],
                colorbar_position="bottom",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_projection = fig.add_subplot(grid[2, :])
            ax_series = fig.add_subplot(grid[3, :], sharex=ax_projection)
            ax_hv = fig.add_subplot(grid[4, :], sharex=ax_projection)
            ax_thrust_components = fig.add_subplot(grid[5, :], sharex=ax_projection)
            cbar_orientation: Literal["vertical", "horizontal"] = "horizontal"
        else:
            grid = fig.add_gridspec(
                8,
                1,
                height_ratios=(3.0, 3.0, 3.0, 3.0, 1.3, 1.3, 1.3, 1.3),
                hspace=0.20,
            )
            ax_compare, cax_compare, lax_compare = _create_spatial_axes(
                fig,
                grid[0, 0],
                colorbar_position="right",
            )
            ax_speed, cax_speed, lax_speed = _create_spatial_axes(
                fig,
                grid[1, 0],
                colorbar_position="right",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_thrust, cax_thrust, lax_thrust = _create_spatial_axes(
                fig,
                grid[2, 0],
                colorbar_position="right",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_vectors, cax_vectors, lax_vectors = _create_spatial_axes(
                fig,
                grid[3, 0],
                colorbar_position="right",
                sharex=ax_compare,
                sharey=ax_compare,
            )
            ax_projection = fig.add_subplot(grid[4, 0])
            ax_series = fig.add_subplot(grid[5, 0], sharex=ax_projection)
            ax_hv = fig.add_subplot(grid[6, 0], sharex=ax_projection)
            ax_thrust_components = fig.add_subplot(grid[7, 0], sharex=ax_projection)
            cbar_orientation = "vertical"

        _draw_trajectory_comparison_spatial_panel(
            fig,
            ax_compare,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax_compare,
            legend_ax=lax_compare,
            cbar_orientation=cbar_orientation,
            title="Trajectory comparison",
            show_xlabel=False,
        )
        _draw_spatial_panel(
            fig,
            ax_speed,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax_speed,
            legend_ax=lax_speed,
            cbar_orientation=cbar_orientation,
            color_mode="speed",
            title="Trajectory by speed",
            show_xlabel=False,
        )
        _draw_spatial_panel(
            fig,
            ax_thrust,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax_thrust,
            legend_ax=lax_thrust,
            cbar_orientation=cbar_orientation,
            color_mode="thrust",
            title="Trajectory by thrust",
            show_xlabel=False,
        )
        _draw_vector_spatial_panel(
            fig,
            ax_vectors,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax_vectors,
            legend_ax=lax_vectors,
            cbar_orientation=cbar_orientation,
            title="Thrust direction vectors (time-sampled)",
            show_xlabel=False,
        )
        _draw_ballistic_projection_timeseries_panel(
            ax_projection,
            ctx=ctx,
            events=events,
            target=target,
            title="Ballistic target projection",
            show_xlabel=False,
        )
        _draw_speed_thrust_timeseries_panel(
            ax_series,
            ctx=ctx,
            events=events,
            title="Speed + thrust over time",
            show_xlabel=False,
        )
        _draw_hv_timeseries_panel(
            ax_hv,
            ctx=ctx,
            events=events,
            title="Horizontal/vertical velocity",
            show_xlabel=False,
        )
        _draw_thrust_component_timeseries_panel(
            ax_thrust_components,
            ctx=ctx,
            events=events,
            title="Horizontal/vertical thrust components",
            show_xlabel=False,
        )

        fig.subplots_adjust(left=0.065, right=0.96, bottom=0.05, top=0.97)
    else:
        fig_w, fig_h = _compute_figure_size(ctx.span_x, ctx.span_y, layout="single")
        colorbar_position = _spatial_colorbar_position(ctx.span_x, ctx.span_y)
        fig = plt.figure(figsize=(fig_w, fig_h))
        grid = fig.add_gridspec(1, 1)
        ax, cax, legend_ax = _create_spatial_axes(
            fig,
            grid[0, 0],
            colorbar_position=colorbar_position,
        )
        cbar_orientation = "horizontal" if colorbar_position == "bottom" else "vertical"
        if mode == "thrust":
            _draw_vector_spatial_panel(
                fig,
                ax,
                ctx=ctx,
                events=events,
                target=target,
                cax=cax,
                legend_ax=legend_ax,
                cbar_orientation=cbar_orientation,
                title="Lander trajectory thrust vectors",
                show_xlabel=True,
            )
        else:
            _draw_spatial_panel(
                fig,
                ax,
                ctx=ctx,
                events=events,
                target=target,
                cax=cax,
                legend_ax=legend_ax,
                cbar_orientation=cbar_orientation,
                color_mode="speed",
                title="Lander trajectory (speed-colored)",
                show_xlabel=True,
            )
        fig.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.96)

    return _save_figure(fig, out_file, max_side_px=max_side_px)


def _render_split_plots(
    *,
    ctx: _PlotContext,
    mode: Literal["speed", "thrust", "all"],
    out_dir: Path,
    max_side_px: int,
    events: list[dict[str, float | str | None]] | None,
    target: dict[str, float | str | None] | None,
) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_paths: list[str] = []
    colorbar_position = _spatial_colorbar_position(ctx.span_x, ctx.span_y)
    cbar_orientation: Literal["vertical", "horizontal"] = (
        "horizontal" if colorbar_position == "bottom" else "vertical"
    )

    def _new_spatial() -> tuple[Any, tuple[Any, Any, Any]]:
        w, h = _compute_figure_size(ctx.span_x, ctx.span_y, layout="single")
        fig = plt.figure(figsize=(w, h))
        gs = fig.add_gridspec(1, 1)
        ax, cax, legend_ax = _create_spatial_axes(
            fig,
            gs[0, 0],
            colorbar_position=colorbar_position,
        )
        return fig, (ax, cax, legend_ax)

    if mode in {"speed", "all"}:
        if mode == "all":
            fig, (ax, cax, legend_ax) = _new_spatial()
            _draw_trajectory_comparison_spatial_panel(
                fig,
                ax,
                ctx=ctx,
                events=events,
                target=target,
                cax=cax,
                legend_ax=legend_ax,
                cbar_orientation=cbar_orientation,
                title="Trajectory comparison",
            )
            fig.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.96)
            out_paths.append(
                _save_figure(
                    fig,
                    out_dir / "spatial_trajectory_comparison.png",
                    max_side_px=max_side_px,
                )
            )
        fig, (ax, cax, legend_ax) = _new_spatial()
        _draw_spatial_panel(
            fig,
            ax,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax,
            legend_ax=legend_ax,
            cbar_orientation=cbar_orientation,
            color_mode="speed",
            title="Trajectory by speed",
        )
        fig.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.96)
        out_paths.append(
            _save_figure(fig, out_dir / "spatial_speed.png", max_side_px=max_side_px)
        )

    if mode in {"thrust", "all"}:
        fig, (ax, cax, legend_ax) = _new_spatial()
        _draw_spatial_panel(
            fig,
            ax,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax,
            legend_ax=legend_ax,
            cbar_orientation=cbar_orientation,
            color_mode="thrust",
            title="Trajectory by thrust",
        )
        fig.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.96)
        out_paths.append(
            _save_figure(fig, out_dir / "spatial_thrust.png", max_side_px=max_side_px)
        )

        fig, (ax, cax, legend_ax) = _new_spatial()
        _draw_vector_spatial_panel(
            fig,
            ax,
            ctx=ctx,
            events=events,
            target=target,
            cax=cax,
            legend_ax=legend_ax,
            cbar_orientation=cbar_orientation,
            title="Thrust direction vectors (time-sampled)",
        )
        fig.subplots_adjust(left=0.08, right=0.95, bottom=0.08, top=0.96)
        out_paths.append(
            _save_figure(
                fig, out_dir / "spatial_thrust_vectors.png", max_side_px=max_side_px
            )
        )

    if mode == "all":
        ts_w, ts_h = _compute_figure_size(ctx.span_x, ctx.span_y, layout="series")

        fig, ax = plt.subplots(figsize=(ts_w, ts_h))
        _draw_ballistic_projection_timeseries_panel(
            ax,
            ctx=ctx,
            events=events,
            target=target,
            title="Ballistic target projection",
            show_xlabel=True,
        )
        fig.tight_layout()
        out_paths.append(
            _save_figure(
                fig,
                out_dir / "timeseries_ballistic_projection.png",
                max_side_px=max_side_px,
            )
        )

        fig, ax = plt.subplots(figsize=(ts_w, ts_h))
        _draw_speed_thrust_timeseries_panel(
            ax,
            ctx=ctx,
            events=events,
            title="Speed + thrust over time",
            show_xlabel=True,
        )
        fig.tight_layout()
        out_paths.append(
            _save_figure(
                fig, out_dir / "timeseries_speed_thrust.png", max_side_px=max_side_px
            )
        )

        fig, ax = plt.subplots(figsize=(ts_w, ts_h))
        _draw_hv_timeseries_panel(
            ax,
            ctx=ctx,
            events=events,
            title="Horizontal/vertical velocity",
            show_xlabel=True,
        )
        fig.tight_layout()
        out_paths.append(
            _save_figure(
                fig, out_dir / "timeseries_hv_speed.png", max_side_px=max_side_px
            )
        )

        fig, ax = plt.subplots(figsize=(ts_w, ts_h))
        _draw_thrust_component_timeseries_panel(
            ax,
            ctx=ctx,
            events=events,
            title="Horizontal/vertical thrust components",
            show_xlabel=True,
        )
        fig.tight_layout()
        out_paths.append(
            _save_figure(
                fig,
                out_dir / "timeseries_thrust_components.png",
                max_side_px=max_side_px,
            )
        )

    return out_paths


def save_trajectory_plots(
    terrain,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    mode: Literal["speed", "thrust", "all"] = "speed",
    *,
    output_profile: PlotOutputProfile = "combined",
    out_dir: str | None = None,
    out_path: str | None = None,
    overview_dir: str | None = None,
    max_side_px: int = 1800,
    events: list[dict[str, float | str | None]] | None = None,
    target: dict[str, float | str | None] | None = None,
    selector_tag: str | None = None,
) -> dict[str, Any]:
    """Save one or more trajectory plot PNGs and return artifact metadata."""
    resolved_mode: Literal["speed", "thrust", "all"] = (
        "all" if mode == "all" else ("thrust" if mode == "thrust" else "speed")
    )
    profile = str(output_profile or "combined").strip().lower()
    if profile not in {"combined", "split", "both"}:
        profile = "combined"

    ctx = _build_plot_context(terrain, samples, target=target)
    resolved_max_side = max(256, int(max_side_px))

    include_manifest = True
    if out_dir is not None:
        bundle_dir = Path(out_dir)
        bundle_dir.mkdir(parents=True, exist_ok=True)
    elif out_path is not None and profile == "combined":
        bundle_dir = Path(out_path).resolve().parent
        bundle_dir.mkdir(parents=True, exist_ok=True)
        include_manifest = False
    else:
        import datetime as _dt

        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = sanitize_token(selector_tag or "run")
        root = Path("outputs") / "plots"
        bundle_dir = _collision_safe_dir(root / f"{tag}_{ts}")
        bundle_dir.mkdir(parents=True, exist_ok=True)

    plot_paths: list[str] = []

    if profile in {"combined", "both"}:
        if out_path and profile == "combined":
            combined_file = Path(out_path)
        elif overview_dir:
            import datetime as _dt

            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            overview_root = Path(overview_dir)
            overview_root.mkdir(parents=True, exist_ok=True)
            base = sanitize_token(selector_tag or "run")
            combined_file = _collision_safe_path(overview_root / f"{base}_{ts}.png")
        else:
            combined_file = bundle_dir / "overview_combined.png"
        plot_paths.append(
            _render_combined_plot(
                ctx=ctx,
                mode=resolved_mode,
                out_file=combined_file,
                max_side_px=resolved_max_side,
                events=events,
                target=target,
            )
        )

    if profile in {"split", "both"}:
        plot_paths.extend(
            _render_split_plots(
                ctx=ctx,
                mode=resolved_mode,
                out_dir=bundle_dir,
                max_side_px=resolved_max_side,
                events=events,
                target=target,
            )
        )

    # Preserve insertion order and remove duplicates.
    deduped_paths: list[str] = []
    seen: set[str] = set()
    for path_str in plot_paths:
        norm = str(Path(path_str))
        if norm in seen:
            continue
        seen.add(norm)
        deduped_paths.append(norm)

    out: dict[str, Any] = {
        "plot_paths": deduped_paths,
    }
    if include_manifest:
        manifest_path = bundle_dir / "manifest.json"
        manifest_payload = {
            "selector_tag": sanitize_token(selector_tag or "run"),
            "plot_mode": resolved_mode,
            "plot_output": profile,
            "plot_max_side_px": resolved_max_side,
            "plot_count": len(deduped_paths),
            "plots": [
                {
                    "path": path,
                    "filename": Path(path).name,
                }
                for path in deduped_paths
            ],
            "events": list(events or []),
            "target": (dict(target) if target is not None else None),
        }
        manifest_path.write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        out["plot_manifest_path"] = str(manifest_path)
        out["plot_bundle_dir"] = str(bundle_dir)
    if deduped_paths:
        out["plot_path"] = deduped_paths[0]
    return out


def save_trajectory_plot(
    terrain,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    mode: Literal["speed", "thrust", "all"] = "speed",
    out_path: str | None = None,
    events: list[dict[str, float | str | None]] | None = None,
    target: dict[str, float | str | None] | None = None,
) -> str:
    """Backward-compatible wrapper returning a single primary PNG path."""
    if out_path is None:
        out_path = str(Path("outputs") / "trajectory.png")
    result = save_trajectory_plots(
        terrain,
        samples,
        mode=mode,
        output_profile="combined",
        out_path=out_path,
        events=events,
        target=target,
        selector_tag="trajectory",
    )
    return str(result.get("plot_path") or out_path)


class Plotter:
    """Collect trajectory samples and write plots at run end."""

    def __init__(
        self,
        terrain,
        lander,
        *,
        enabled: bool = False,
        mode: PlotMode = "none",
        output_profile: PlotOutputProfile = "combined",
        max_side_px: int = 1800,
    ) -> None:
        self.enabled = enabled
        self.mode: PlotMode = mode
        self.output_profile: PlotOutputProfile = output_profile
        self.max_side_px = max(256, int(max_side_px))
        self.terrain = terrain
        self.lander = lander
        self._selector_tag: str = "run"
        self._samples: list[
            tuple[float, float, float, float, float, float, float, float]
        ] = []
        self._events: list[dict[str, float | str | None]] = []
        self._target: dict[str, float | str | None] | None = None
        self._sample_period_s: float = 1.0
        self._sample_time_s: float = 0.0
        self._time_accum: float = 0.0
        self._sampling_enabled: bool = bool(self.enabled and self.mode != "none")

    def set_mode(self, mode: PlotMode) -> None:
        self.mode = mode
        self._sampling_enabled = bool(self.enabled and self.mode != "none")

    def set_output_profile(self, output_profile: PlotOutputProfile) -> None:
        mode = str(output_profile or "combined").strip().lower()
        if mode not in {"combined", "split", "both"}:
            mode = "combined"
        self.output_profile = mode  # type: ignore[assignment]

    def set_selector_tag(self, tag: str) -> None:
        self._selector_tag = sanitize_token(tag)

    def set_sampling_from_print_freq(self, print_freq: int, target_fps: float) -> None:
        if print_freq and print_freq > 0 and target_fps > 0:
            frames = max(1, int(print_freq))
            self._sample_period_s = frames / float(target_fps)
        else:
            self._sample_period_s = 1.0

    def set_target(
        self,
        *,
        x: float,
        y: float,
        label: str = "target",
        size: float | None = None,
    ) -> None:
        if not self._sampling_enabled:
            return
        self._target = {
            "x": float(x),
            "y": float(y),
            "label": str(label),
            "size": None if size is None else float(size),
        }

    def set_plot_max_side_px(self, value: int) -> None:
        self.max_side_px = max(256, int(value))

    def seed_initial_sample(self) -> None:
        if not self._sampling_enabled:
            return
        self._samples.clear()
        self._events.clear()
        self._time_accum = 0.0
        self._sample_time_s = 0.0
        self._record_sample()

    def update(self, dt: float) -> None:
        if not self._sampling_enabled:
            return
        self._time_accum += dt
        while self._time_accum >= self._sample_period_s:
            self._time_accum -= self._sample_period_s
            self._sample_time_s += self._sample_period_s
            self._record_sample()

    def _record_sample(self) -> None:
        trans = require_component(self.lander, Transform)
        phys = require_component(self.lander, PhysicsState)
        eng = require_component(self.lander, Engine)
        speed = (phys.vel.x * phys.vel.x + phys.vel.y * phys.vel.y) ** 0.5
        self._samples.append(
            (
                trans.pos.x,
                trans.pos.y,
                speed,
                eng.thrust_level,
                trans.rotation,
                self._sample_time_s,
                phys.vel.x,
                phys.vel.y,
            )
        )

    def get_samples(
        self,
    ) -> list[tuple[float, float, float, float, float, float, float, float]]:
        return list(self._samples)

    def mark_event(
        self,
        *,
        name: str,
        x: float,
        y: float,
        label: str | None = None,
        metadata: dict[str, float | str | None] | None = None,
    ) -> None:
        if not self._sampling_enabled:
            return
        event_payload: dict[str, float | str | None] = {
            "name": str(name),
            "x": float(x),
            "y": float(y),
            "label": label if label is None else str(label),
        }
        for key, value in (metadata or {}).items():
            if not isinstance(key, str):
                continue
            event_payload[str(key)] = value
        self._events.append(event_payload)

    def _build_outcome_event(self) -> dict[str, float | str | None] | None:
        if not self._sampling_enabled:
            return None
        state = self.lander.get_component(LanderState)
        tank = self.lander.get_component(FuelTank)
        trans = self.lander.get_component(Transform)
        if state is None or trans is None:
            return None
        state_name = str(state.state)
        if (
            state_name not in {"landed", "crashed"}
            and tank is not None
            and tank.fuel <= 0.0
        ):
            state_name = "out_of_fuel"
        outcome_name: str | None = None
        outcome_label: str | None = None
        if state_name == "landed":
            outcome_name = "success"
            outcome_label = "landed"
        elif state_name == "crashed":
            outcome_name = "crash"
            outcome_label = "crash"
        elif state_name == "out_of_fuel":
            outcome_name = "out_of_fuel"
            outcome_label = "fuel out"
        if outcome_name is None:
            return None
        event_time_s = self._sample_time_s + max(0.0, self._time_accum)
        return {
            "name": outcome_name,
            "x": float(trans.pos.x),
            "y": float(trans.pos.y),
            "label": outcome_label,
            "time_s": float(event_time_s),
        }

    def finalize(self) -> dict:
        if not self.enabled:
            return {}
        mode = self.mode or "none"
        if mode == "none":
            return {}
        try:
            import datetime as _dt

            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            resolved_mode: Literal["speed", "thrust", "all"]
            if mode in ("speed", "thrust", "all"):
                resolved_mode = mode
            else:
                resolved_mode = "speed"
            tag = sanitize_token(self._selector_tag)
            bundle_dir = _collision_safe_dir(Path("outputs") / "plots" / f"{tag}_{ts}")
            events = list(self._events)
            outcome_event = self._build_outcome_event()
            if outcome_event is not None:
                events.append(outcome_event)
            return save_trajectory_plots(
                self.terrain,
                self._samples,
                mode=resolved_mode,
                output_profile=self.output_profile,
                out_dir=str(bundle_dir),
                overview_dir=str(Path("outputs") / "plots" / "overview"),
                max_side_px=self.max_side_px,
                events=events,
                target=self._target,
                selector_tag=tag,
            )
        except Exception as e:  # pragma: no cover - plotting optional
            return {"plot_error": str(e)}
