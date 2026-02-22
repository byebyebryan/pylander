"""Headless trajectory plotting utilities.

Provides functions to render terrain (LOD 0) and a trajectory colored by
speed or thrust level, saving to a PNG file via the Agg backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from core.components import Engine, PhysicsState, Transform


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


def save_trajectory_plot(
    terrain,
    samples: list[tuple[float, float, float, float]],
    mode: Literal["speed", "thrust"] = "speed",
    out_path: str | None = None,
) -> str:
    """Save a PNG plot of terrain (LOD 0) and a colored trajectory.

    Args:
        terrain: Terrain instance with .sample(x, lod=0)
        samples: list of (x, y, speed, thrust) tuples
        mode: color mode: "speed" or "thrust"
        out_path: optional explicit output path

    Returns:
        Output file path.
    """
    if out_path is None:
        out_path = str(Path("outputs") / "trajectory.png")

    if len(samples) < 2:
        # duplicate last point to create a segment for plotting
        if samples:
            samples = samples + [samples[-1]]
        else:
            samples = [(0.0, 0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)]

    xs = [p[0] for p in samples]
    ys = [p[1] for p in samples]
    speeds = [p[2] for p in samples]
    thrusts = [p[3] for p in samples]

    # Determine terrain sampling range with padding
    min_x = min(xs)
    max_x = max(xs)
    pad = 200.0
    min_x -= pad
    max_x += pad
    if max_x <= min_x:
        max_x = min_x + 1.0

    # Choose a sampling interval compatible with terrain LOD 0
    base_interval = terrain.get_resolution(0)
    # Anchor to base grid
    import math as _math

    start_x = _math.floor(min_x / base_interval) * base_interval
    end_x = _math.ceil(max_x / base_interval) * base_interval
    terrain_xs: list[float] = []
    xx = start_x
    while xx <= end_x:
        terrain_xs.append(xx)
        xx += base_interval
    terrain_ys = [terrain(x, lod=0) for x in terrain_xs]

    # Plot using Agg backend
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    import numpy as np

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    # Terrain polyline
    ax.plot(
        terrain_xs,
        terrain_ys,
        color="#444444",
        linewidth=1.0,
        alpha=0.8,
        label="terrain (LOD 0)",
    )

    # Trajectory colored by chosen scalar
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
        if vmax <= 0:
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

    # Bounds
    all_y = terrain_ys + ys
    y_min = min(all_y)
    y_max = max(all_y)
    y_pad = 0.05 * max(1.0, (y_max - y_min))
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    ax.set_xlabel("x (world units)")
    ax.set_ylabel("y (world units)")
    ax.set_title(f"Lander trajectory ({mode}-colored) with terrain LOD 0")
    ax.legend(loc="upper right")
    ax.grid(True, linestyle=":", alpha=0.3)

    fig.tight_layout()
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file)
    plt.close(fig)
    return str(out_file)


class Plotter:
    """Collects trajectory samples and writes plots at the end of a headless run.

    Usage:
        plotter = Plotter(terrain, lander, enabled=headless, mode=level.plot_mode)
        plotter.set_sampling_from_print_freq(print_freq, target_fps)
        plotter.seed_initial_sample()
        ... each frame ...
        plotter.update(dt)
        ... on shutdown ...
        extras = plotter.finalize()
    """

    def __init__(
        self,
        terrain,
        lander,
        *,
        enabled: bool = False,
        mode: Literal["none", "speed", "thrust", "all"] = "none",
    ) -> None:
        self.enabled = enabled
        self.mode: Literal["none", "speed", "thrust", "all"] = mode
        self.terrain = terrain
        self.lander = lander
        self._samples: list[tuple[float, float, float, float]] = []
        self._sample_period_s: float = 1.0
        self._time_accum: float = 0.0

    def set_mode(self, mode: Literal["none", "speed", "thrust", "all"]) -> None:
        self.mode = mode

    def set_sampling_from_print_freq(self, print_freq: int, target_fps: float) -> None:
        """Configure sampling period using print frequency and a reference FPS.

        If print_freq <= 0, defaults to 1.0s. Otherwise, samples every N frames,
        i.e., period = max(1, print_freq) / target_fps seconds.
        """
        if print_freq and print_freq > 0 and target_fps > 0:
            frames = max(1, int(print_freq))
            self._sample_period_s = frames / float(target_fps)
        else:
            self._sample_period_s = 1.0

    def seed_initial_sample(self) -> None:
        if not self.enabled:
            return
        self._samples.clear()
        self._time_accum = 0.0
        self._record_sample()

    def update(self, dt: float) -> None:
        if not self.enabled:
            return
        self._time_accum += dt
        while self._time_accum >= self._sample_period_s:
            self._time_accum -= self._sample_period_s
            self._record_sample()

    def _record_sample(self) -> None:
        trans = _require_component(self.lander, Transform)
        phys = _require_component(self.lander, PhysicsState)
        eng = _require_component(self.lander, Engine)
        speed = (phys.vel.x * phys.vel.x + phys.vel.y * phys.vel.y) ** 0.5
        self._samples.append((trans.pos.x, trans.pos.y, speed, eng.thrust_level))

    def get_samples(self) -> list[tuple[float, float, float, float]]:
        return list(self._samples)

    def finalize(self) -> dict:
        """Write plot files if enabled and a plotting mode is selected.

        Returns a dict suitable for merging into the game's result summary.
        Keys may include: "plot_path", "plot_paths", or "plot_error".
        """
        if not self.enabled:
            return {}
        mode = self.mode or "none"
        if mode == "none":
            return {}
        try:
            import datetime as _dt

            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            if mode == "all":
                paths: list[str] = []
                for m in ("speed", "thrust"):
                    out_path = str(Path("outputs") / f"trajectory_{ts}_{m}.png")
                    save_trajectory_plot(
                        self.terrain, self._samples, mode=m, out_path=out_path
                    )
                    paths.append(out_path)
                return {"plot_paths": paths}
            else:
                m = "speed" if mode not in ("speed", "thrust") else mode
                out_path = str(Path("outputs") / f"trajectory_{ts}_{m}.png")
                save_trajectory_plot(
                    self.terrain, self._samples, mode=m, out_path=out_path
                )
                return {"plot_path": out_path}
        except Exception as e:  # pragma: no cover - plotting optional
            return {"plot_error": str(e)}
