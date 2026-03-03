"""Headless trajectory plotting utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.components import Engine, PhysicsState, Transform
from core.ecs import require_component


PlotMode = Literal["none", "speed", "thrust", "all"]


def _compute_figure_size(span_x: float, span_y: float, *, with_series: bool) -> tuple[float, float]:
    ratio = max(1e-6, span_x) / max(1e-6, span_y)
    traj_height = 5.4
    traj_width = traj_height * max(1.6, min(4.8, ratio))
    fig_height = traj_height + (1.9 if with_series else 0.0)
    return max(10.0, min(26.0, traj_width)), fig_height


def save_trajectory_plot(
    terrain,
    samples: list[tuple[float, float, float, float]],
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
            samples = [(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)]

    xs = [p[0] for p in samples]
    ys = [p[1] for p in samples]
    speeds = [p[2] for p in samples]
    thrusts = [p[3] for p in samples]

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

    with_series = mode == "all"
    fig_w, fig_h = _compute_figure_size(span_x, span_y, with_series=with_series)
    if with_series:
        fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)
        grid = fig.add_gridspec(2, 1, height_ratios=(4.0, 1.35), hspace=0.2)
        ax = fig.add_subplot(grid[0])
        ax_series = fig.add_subplot(grid[1])
    else:
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=150)
        ax_series = None

    ax.plot(
        terrain_xs,
        terrain_ys,
        color="#444444",
        linewidth=1.0,
        alpha=0.85,
        label="terrain",
    )

    points = np.column_stack([xs, ys])
    segments = np.stack([points[:-1], points[1:]], axis=1)

    if mode == "thrust":
        vals = 0.5 * (np.array(thrusts[:-1]) + np.array(thrusts[1:]))
        cmap = "Blues"
        vmin, vmax = 0.0, 1.0
        cbar_label = "thrust (0..1)"
    else:
        vals = 0.5 * (np.array(speeds[:-1]) + np.array(speeds[1:]))
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
    cbar = fig.colorbar(lc, ax=ax, pad=0.01)
    cbar.set_label(cbar_label)

    dxy = np.diff(points, axis=0)
    lengths = np.hypot(dxy[:, 0], dxy[:, 1])
    valid = lengths > 1e-6
    if np.any(valid):
        mids = points[:-1] + (0.5 * dxy)
        dirs = np.zeros_like(dxy)
        dirs[valid] = dxy[valid] / lengths[valid, None]
        arrow_len = 0.03 * max(span_x, span_y, 1.0)
        valid_ids = np.where(valid)[0]
        stride = max(1, len(valid_ids) // 42)
        pick = valid_ids[::stride]
        ax.quiver(
            mids[pick, 0],
            mids[pick, 1],
            dirs[pick, 0] * arrow_len,
            dirs[pick, 1] * arrow_len,
            angles="xy",
            scale_units="xy",
            scale=1.0,
            width=0.0022,
            headwidth=4.5,
            headlength=6.0,
            headaxislength=4.6,
            color="#222222",
            alpha=0.32,
            zorder=4,
        )

    event_list = list(events or [])
    if event_list:
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

    if target is not None:
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

    ax.set_xlim(min_x, max_x)
    ax.set_ylim(lower_y, upper_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (world units)")
    ax.set_ylabel("y (world units)")
    if mode == "all":
        ax.set_title("Lander trajectory (speed color) with thrust/speed profile")
    else:
        ax.set_title(f"Lander trajectory ({mode}-colored)")
    ax.grid(True, linestyle=":", alpha=0.3)
    ax.legend(loc="upper right")

    if ax_series is not None:
        import numpy as np

        t = np.arange(len(samples), dtype=float)
        speed_line, = ax_series.plot(t, speeds, color="#d62728", linewidth=1.25, label="speed")
        ax_series.set_ylabel("speed")
        ax_series.grid(True, linestyle=":", alpha=0.25)

        ax_thrust = ax_series.twinx()
        thrust_line, = ax_thrust.plot(
            t, thrusts, color="#1f77b4", linewidth=1.15, alpha=0.92, label="thrust"
        )
        ax_thrust.set_ylabel("thrust")
        max_thrust = max(thrusts) if thrusts else 1.0
        ax_thrust.set_ylim(0.0, max(1.0, max_thrust * 1.05))
        ax_series.set_xlabel("sample index")
        ax_series.legend([speed_line, thrust_line], ["speed", "thrust"], loc="upper right")

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
        self._samples: list[tuple[float, float, float, float]] = []
        self._events: list[dict[str, float | str | None]] = []
        self._target: dict[str, float | str | None] | None = None
        self._sample_period_s: float = 1.0
        self._time_accum: float = 0.0
        self._sampling_enabled: bool = bool(self.enabled and self.mode != "none")

    def set_mode(self, mode: PlotMode) -> None:
        self.mode = mode
        self._sampling_enabled = bool(self.enabled and self.mode != "none")

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
        self._record_sample()

    def update(self, dt: float) -> None:
        if not self._sampling_enabled:
            return
        self._time_accum += dt
        while self._time_accum >= self._sample_period_s:
            self._time_accum -= self._sample_period_s
            self._record_sample()

    def _record_sample(self) -> None:
        trans = require_component(self.lander, Transform)
        phys = require_component(self.lander, PhysicsState)
        eng = require_component(self.lander, Engine)
        speed = (phys.vel.x * phys.vel.x + phys.vel.y * phys.vel.y) ** 0.5
        self._samples.append((trans.pos.x, trans.pos.y, speed, eng.thrust_level))

    def get_samples(self) -> list[tuple[float, float, float, float]]:
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
            out_path = str(Path("outputs") / f"trajectory_{ts}_{resolved_mode}.png")
            save_trajectory_plot(
                self.terrain,
                self._samples,
                mode=resolved_mode,
                out_path=out_path,
                events=self._events,
                target=self._target,
            )
            return {"plot_path": out_path}
        except Exception as e:  # pragma: no cover - plotting optional
            return {"plot_error": str(e)}

