"""Headless trajectory plotting utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.components import Engine, PhysicsState, Transform
from core.ecs import require_component


PlotMode = Literal["none", "speed", "thrust", "all"]


def _sanitize_filename_token(token: str) -> str:
    out_chars: list[str] = []
    prev_underscore = False
    for ch in token.strip().lower():
        keep = ch.isalnum() or ch in {"-", "."}
        if keep:
            out_chars.append(ch)
            prev_underscore = False
        else:
            if not prev_underscore:
                out_chars.append("_")
                prev_underscore = True
    sanitized = "".join(out_chars).strip("._")
    if not sanitized:
        return "run"
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    return sanitized


def _collision_safe_path(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _compute_figure_size(
    span_x: float, span_y: float, *, layout: Literal["single", "all"]
) -> tuple[float, float]:
    ratio = max(1e-6, span_x) / max(1e-6, span_y)
    traj_height = 5.4
    traj_width = traj_height * max(1.6, min(4.8, ratio))
    if layout == "all":
        return max(10.0, min(26.0, traj_width)), (traj_height * 3.0) + 4.0
    return max(10.0, min(26.0, traj_width)), traj_height


def save_trajectory_plot(
    terrain,
    samples: list[tuple[float, float, float, float, float, float, float, float]],
    mode: Literal["speed", "thrust", "all"] = "speed",
    out_path: str | None = None,
    events: list[dict[str, float | str | None]] | None = None,
    target: dict[str, float | str | None] | None = None,
) -> str:
    """Save a PNG plot of terrain (LOD 0) and a trajectory."""
    if out_path is None:
        out_path = str(Path("outputs") / "trajectory.png")

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

    min_x = min(xs)
    max_x = max(xs)
    pad = 200.0
    min_x -= pad
    max_x += pad
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
    y_pad = 0.05 * max(1.0, (y_max - y_min))
    lower_y = y_min - y_pad
    upper_y = y_max + y_pad
    span_x = max_x - min_x
    span_y = upper_y - lower_y

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    import numpy as np

    points = np.column_stack([xs, ys])
    segments = np.stack([points[:-1], points[1:]], axis=1)
    thrust_arr = np.array(thrusts, dtype=float)
    speed_arr = np.array(speeds, dtype=float)
    angle_arr = np.array(angles, dtype=float)
    speed_seg_vals = 0.5 * (speed_arr[:-1] + speed_arr[1:])
    thrust_seg_vals = 0.5 * (thrust_arr[:-1] + thrust_arr[1:])

    def _draw_events(ax) -> None:
        event_list = list(events or [])
        if not event_list:
            return
        color_by_name = {
            "setup_gate": "#1f77b4",
            "flare_gate": "#ff7f0e",
            "terminal_gate": "#ff7f0e",
        }
        labeled_kinds: set[str] = set()
        for event in event_list:
            raw_name = event.get("name")
            event_name = str(raw_name) if isinstance(raw_name, str) and raw_name else "event"
            event_x = float(event.get("x", 0.0) or 0.0)
            event_y = float(event.get("y", 0.0) or 0.0)
            color = color_by_name.get(event_name, "#222222")
            legend_label = event_name.replace("_", " ")
            scatter_label = legend_label if event_name not in labeled_kinds else None
            labeled_kinds.add(event_name)
            ax.scatter(
                [event_x],
                [event_y],
                s=44.0,
                marker="o",
                color=color,
                edgecolors="#FFFFFF",
                linewidths=0.8,
                zorder=6,
                label=scatter_label,
            )
            raw_label = event.get("label")
            text_label = str(raw_label) if isinstance(raw_label, str) and raw_label else legend_label
            ax.annotate(
                text_label,
                xy=(event_x, event_y),
                xytext=(5, 6),
                textcoords="offset points",
                fontsize=7,
                color=color,
                zorder=7,
            )

    def _draw_target(ax) -> None:
        if target is None:
            return
        try:
            target_x = float(target.get("x", 0.0) or 0.0)
            target_y = float(target.get("y", 0.0) or 0.0)
        except (TypeError, ValueError):
            target_x = 0.0
            target_y = 0.0
        target_label_raw = target.get("label", "target")
        target_label = str(target_label_raw) if target_label_raw else "target"
        ax.scatter(
            [target_x],
            [target_y],
            s=120.0,
            marker="*",
            color="#2ca02c",
            edgecolors="#FFFFFF",
            linewidths=0.9,
            zorder=7,
            label=target_label,
        )

    def _vector_sample_indices() -> list[int]:
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

    vector_indices = _vector_sample_indices()

    def _draw_spatial(
        ax,
        *,
        cax=None,
        color_mode: Literal["speed", "thrust"],
        title: str,
    ) -> None:
        ax.plot(
            terrain_xs,
            terrain_ys,
            color="#444444",
            linewidth=1.0,
            alpha=0.85,
            label="terrain",
        )
        if color_mode == "thrust":
            vals = thrust_seg_vals
            cmap = "Blues"
            vmin, vmax = 0.0, 1.0
            cbar_label = "thrust (0..1)"
        else:
            vals = speed_seg_vals
            vmax = float(vals.max() if vals.size > 0 else 1.0)
            if vmax <= 0.0:
                vmax = 1.0
            vmin = 0.0
            cmap = "RdYlGn_r"
            cbar_label = "speed (world units/s)"
        lc = LineCollection(segments, cmap=cmap, norm=plt.Normalize(vmin=vmin, vmax=vmax))
        lc.set_array(vals)
        lc.set_linewidth(2.0)
        ax.add_collection(lc)
        cbar = (
            fig.colorbar(lc, cax=cax)
            if cax is not None
            else fig.colorbar(lc, ax=ax, pad=0.01)
        )
        cbar.set_label(cbar_label)

        _draw_events(ax)
        _draw_target(ax)
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(lower_y, upper_y)
        ax.set_aspect("equal", adjustable="box")
        ax.set_anchor("W")
        ax.set_xlabel("x (world units)")
        ax.set_ylabel("y (world units)")
        ax.set_title(title)
        ax.grid(True, linestyle=":", alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc="upper right", fontsize=8)

    def _draw_vector_spatial(ax, *, cax=None, title: str) -> None:
        ax.plot(
            terrain_xs,
            terrain_ys,
            color="#444444",
            linewidth=1.0,
            alpha=0.85,
            label="terrain",
        )
        ax.plot(xs, ys, color="#777777", linewidth=1.25, alpha=0.42, label="trajectory")

        vector_len = 0.038 * max(span_x, span_y, 1.0)
        vx_dir = np.sin(angle_arr)
        vy_dir = np.cos(angle_arr)
        sampled = np.array(vector_indices, dtype=int)
        sampled_thrust = thrust_arr[sampled]
        sampled_x = points[sampled, 0]
        sampled_y = points[sampled, 1]

        active_mask = sampled_thrust > 0.01
        if np.any(active_mask):
            idx = sampled[active_mask]
            q = ax.quiver(
                points[idx, 0],
                points[idx, 1],
                vx_dir[idx] * vector_len * thrust_arr[idx],
                vy_dir[idx] * vector_len * thrust_arr[idx],
                thrust_arr[idx],
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
                cbar = fig.colorbar(q, cax=cax)
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

        _draw_events(ax)
        _draw_target(ax)
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(lower_y, upper_y)
        ax.set_aspect("equal", adjustable="box")
        ax.set_anchor("W")
        ax.set_xlabel("x (world units)")
        ax.set_ylabel("y (world units)")
        ax.set_title(title)
        ax.grid(True, linestyle=":", alpha=0.3)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, loc="upper right", fontsize=8)

    if mode == "all":
        fig_w, fig_h = _compute_figure_size(span_x, span_y, layout="all")
        fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)
        grid = fig.add_gridspec(
            5,
            2,
            width_ratios=(1.0, 0.055),
            height_ratios=(2.8, 2.8, 2.8, 1.3, 1.3),
            hspace=0.16,
            wspace=0.08,
        )
        ax_speed = fig.add_subplot(grid[0, 0])
        cax_speed = fig.add_subplot(grid[0, 1])
        ax_thrust = fig.add_subplot(grid[1, 0], sharex=ax_speed, sharey=ax_speed)
        cax_thrust = fig.add_subplot(grid[1, 1])
        ax_vectors = fig.add_subplot(grid[2, 0], sharex=ax_speed, sharey=ax_speed)
        cax_vectors = fig.add_subplot(grid[2, 1])
        ax_series = fig.add_subplot(grid[3, :])
        ax_hv = fig.add_subplot(grid[4, :], sharex=ax_series)

        _draw_spatial(
            ax_speed,
            cax=cax_speed,
            color_mode="speed",
            title="Trajectory by speed",
        )
        _draw_spatial(
            ax_thrust,
            cax=cax_thrust,
            color_mode="thrust",
            title="Trajectory by thrust",
        )
        _draw_vector_spatial(
            ax_vectors,
            cax=cax_vectors,
            title="Thrust direction vectors (time-sampled)",
        )
        # Keep x-axis labels only on time-series panels to avoid cross-panel title overlap.
        ax_speed.set_xlabel("")
        ax_thrust.set_xlabel("")
        ax_vectors.set_xlabel("")

        t = np.array(sample_times, dtype=float)
        speed_line = ax_series.plot(
            t, speeds, color="#d62728", linewidth=1.2, label="speed"
        )[0]
        ax_series.set_ylabel("speed")
        ax_series.grid(True, linestyle=":", alpha=0.25)

        ax_series_thrust = ax_series.twinx()
        thrust_line = ax_series_thrust.plot(
            t, thrusts, color="#1f77b4", linewidth=1.15, alpha=0.92, label="thrust"
        )[0]
        ax_series_thrust.set_ylabel("thrust")
        max_thrust = max(thrusts) if thrusts else 1.0
        ax_series_thrust.set_ylim(0.0, max(1.0, max_thrust * 1.05))
        ax_series.set_xlabel("")
        ax_series.set_title("Speed + thrust over time")
        ax_series.legend(
            [speed_line, thrust_line],
            ["speed", "thrust"],
            loc="upper right",
            fontsize=8,
        )
        ax_series.tick_params(labelbottom=True)

        ax_hv.plot(t, vxs, color="#2ca02c", linewidth=1.1, label="vx")
        ax_hv.plot(t, vys, color="#9467bd", linewidth=1.1, label="vy_up")
        ax_hv.axhline(0.0, color="#777777", linewidth=0.8, linestyle=":")
        ax_hv.set_xlabel("")
        ax_hv.set_ylabel("velocity")
        ax_hv.set_title("Horizontal/vertical velocity")
        ax_hv.grid(True, linestyle=":", alpha=0.25)
        ax_hv.legend(loc="upper right", fontsize=8)
        ax_hv.tick_params(labelbottom=True)

        fig.subplots_adjust(left=0.065, right=0.94, bottom=0.05, top=0.96, hspace=0.22, wspace=0.08)
    else:
        fig_w, fig_h = _compute_figure_size(span_x, span_y, layout="single")
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
        resolved_mode = "thrust" if mode == "thrust" else "speed"
        if resolved_mode == "thrust":
            _draw_vector_spatial(ax, title="Lander trajectory thrust vectors")
        else:
            _draw_spatial(
                ax,
                color_mode=resolved_mode,
                title=f"Lander trajectory ({resolved_mode}-colored)",
            )
        fig.tight_layout()
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file)
    plt.close(fig)
    return str(out_file)


class Plotter:
    """Collect trajectory samples and write plots at run end."""

    def __init__(
        self,
        terrain,
        lander,
        *,
        enabled: bool = False,
        mode: PlotMode = "none",
    ) -> None:
        self.enabled = enabled
        self.mode: PlotMode = mode
        self.terrain = terrain
        self.lander = lander
        self._selector_tag: str = "run"
        self._samples: list[tuple[float, float, float, float, float, float, float, float]] = []
        self._events: list[dict[str, float | str | None]] = []
        self._target: dict[str, float | str | None] | None = None
        self._sample_period_s: float = 1.0
        self._sample_time_s: float = 0.0
        self._time_accum: float = 0.0
        self._sampling_enabled: bool = bool(self.enabled and self.mode != "none")

    def set_mode(self, mode: PlotMode) -> None:
        self.mode = mode
        self._sampling_enabled = bool(self.enabled and self.mode != "none")

    def set_selector_tag(self, tag: str) -> None:
        self._selector_tag = _sanitize_filename_token(tag)

    def set_sampling_from_print_freq(self, print_freq: int, target_fps: float) -> None:
        if print_freq and print_freq > 0 and target_fps > 0:
            frames = max(1, int(print_freq))
            self._sample_period_s = frames / float(target_fps)
        else:
            self._sample_period_s = 1.0

    def set_target(self, *, x: float, y: float, label: str = "target") -> None:
        if not self._sampling_enabled:
            return
        self._target = {
            "x": float(x),
            "y": float(y),
            "label": str(label),
        }

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

    def get_samples(self) -> list[tuple[float, float, float, float, float, float, float, float]]:
        return list(self._samples)

    def mark_event(
        self,
        *,
        name: str,
        x: float,
        y: float,
        label: str | None = None,
    ) -> None:
        if not self._sampling_enabled:
            return
        self._events.append(
            {
                "name": str(name),
                "x": float(x),
                "y": float(y),
                "label": label if label is None else str(label),
            }
        )

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
            tag = _sanitize_filename_token(self._selector_tag)
            out_file = _collision_safe_path(Path("outputs") / f"{tag}_{ts}.png")
            save_trajectory_plot(
                self.terrain,
                self._samples,
                mode=resolved_mode,
                out_path=str(out_file),
                events=self._events,
                target=self._target,
            )
            return {"plot_path": str(out_file)}
        except Exception as e:  # pragma: no cover - plotting optional
            return {"plot_error": str(e)}
