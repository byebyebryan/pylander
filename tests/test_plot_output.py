from __future__ import annotations

import json
from pathlib import Path

import matplotlib.image as mpimg

from core.components import FlightState, LanderState, Transform
from core.lander import Lander
from core.maths import Vector2
from conftest import FlatTerrain
from utils.plot import (
    _ballistic_projection_series,
    _build_plot_context,
    _combined_spatial_arrangement,
    _compute_figure_size,
    _projected_intercept_from_state,
    _sorted_gate_events,
    Plotter,
    save_trajectory_plots,
)


def _samples() -> list[tuple[float, float, float, float, float, float, float, float]]:
    return [
        (0.0, 120.0, 15.0, 0.2, 0.0, 0.0, 0.0, -12.0),
        (60.0, 100.0, 16.0, 0.4, 0.1, 0.5, 8.0, -13.0),
        (120.0, 70.0, 18.0, 0.7, 0.2, 1.0, 10.0, -15.0),
        (170.0, 30.0, 22.0, 0.1, 0.4, 1.5, 14.0, -20.0),
    ]


def _tall_samples() -> list[tuple[float, float, float, float, float, float, float, float]]:
    return [
        (0.0, 0.0, 8.0, 0.1, 0.0, 0.0, 0.0, 8.0),
        (20.0, 180.0, 9.0, 0.5, 0.1, 0.5, 3.0, 11.0),
        (40.0, 420.0, 10.0, 0.8, 0.2, 1.0, 4.0, 12.0),
        (65.0, 760.0, 11.0, 0.3, 0.3, 1.5, 5.0, 13.0),
    ]


def _shallow_samples() -> list[tuple[float, float, float, float, float, float, float, float]]:
    return [
        (0.0, 0.0, 8.0, 0.2, 0.0, 0.0, 0.0, 3.0),
        (80.0, 12.0, 9.0, 0.4, 0.0, 0.5, 8.0, 2.0),
        (160.0, 18.0, 10.0, 0.5, 0.1, 1.0, 9.0, -1.0),
        (220.0, 5.0, 9.0, 0.1, 0.1, 1.5, 8.0, -3.0),
    ]


def test_save_trajectory_plots_combined_writes_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "combined"
    result = save_trajectory_plots(
        FlatTerrain(),
        _samples(),
        mode="all",
        output_profile="combined",
        out_dir=str(out_dir),
        max_side_px=1200,
        target={"x": 120.0, "y": 0.0, "size": 110.0, "label": "landing target"},
        selector_tag="launch_far_0",
    )

    assert len(result.get("plot_paths") or []) == 1
    assert Path(result["plot_path"]).exists()
    manifest = Path(result["plot_manifest_path"])
    assert manifest.exists()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["plot_output"] == "combined"
    assert payload["plot_count"] == 1
    assert payload["target"]["size"] == 110.0


def test_save_trajectory_plots_split_all_writes_expected_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "split"
    result = save_trajectory_plots(
        FlatTerrain(),
        _samples(),
        mode="all",
        output_profile="split",
        out_dir=str(out_dir),
        max_side_px=1200,
        selector_tag="launch_far_0",
    )

    names = {Path(p).name for p in (result.get("plot_paths") or [])}
    assert {
        "spatial_speed.png",
        "spatial_trajectory_comparison.png",
        "spatial_thrust.png",
        "spatial_thrust_vectors.png",
        "timeseries_ballistic_projection.png",
        "timeseries_speed_thrust.png",
        "timeseries_hv_speed.png",
        "timeseries_thrust_components.png",
    }.issubset(names)
    assert Path(result["plot_manifest_path"]).exists()


def test_save_trajectory_plots_respects_max_side_px(tmp_path: Path) -> None:
    out_dir = tmp_path / "capped"
    result = save_trajectory_plots(
        FlatTerrain(),
        _samples(),
        mode="all",
        output_profile="both",
        out_dir=str(out_dir),
        max_side_px=900,
        selector_tag="launch_far_0",
    )

    image_path = Path((result.get("plot_paths") or [])[0])
    assert image_path.exists()
    image = mpimg.imread(image_path)
    assert max(image.shape[0], image.shape[1]) <= 920


def test_save_trajectory_plots_writes_combined_to_overview_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "bundle"
    overview_dir = tmp_path / "overview"
    result = save_trajectory_plots(
        FlatTerrain(),
        _samples(),
        mode="all",
        output_profile="both",
        out_dir=str(out_dir),
        overview_dir=str(overview_dir),
        max_side_px=1200,
        selector_tag="launch_far_0",
    )
    combined = Path(result["plot_paths"][0])
    assert combined.exists()
    assert str(combined).startswith(str(overview_dir))


def test_combined_spatial_arrangement_uses_columns_for_tall_paths() -> None:
    assert _combined_spatial_arrangement(200.0, 900.0) == "columns"
    assert _combined_spatial_arrangement(900.0, 200.0) == "rows"


def test_build_plot_context_limits_wide_shallow_spatial_ratio() -> None:
    ctx = _build_plot_context(FlatTerrain(), _shallow_samples())
    assert ctx.span_x / ctx.span_y <= 3.2


def test_build_plot_context_widens_tall_spatial_ratio_for_column_layouts() -> None:
    ctx = _build_plot_context(FlatTerrain(), _tall_samples())
    assert ctx.span_x / ctx.span_y >= 1.24


def test_projected_intercept_crosses_target_y_when_reachable() -> None:
    intercept = _projected_intercept_from_state(
        x=0.0,
        y=120.0,
        vx=8.0,
        vy_up=-12.0,
        target_x=80.0,
        target_y=0.0,
    )

    assert intercept.has_target_y_solution is True
    assert intercept.end_y == 0.0


def test_projected_intercept_falls_back_to_apex_when_target_y_is_unreachable() -> None:
    intercept = _projected_intercept_from_state(
        x=10.0,
        y=30.0,
        vx=6.0,
        vy_up=4.0,
        target_x=100.0,
        target_y=80.0,
    )

    assert intercept.has_target_y_solution is False
    assert intercept.end_y < 80.0


def test_ballistic_projection_series_uses_apex_while_climbing_and_current_height_while_descending() -> None:
    climb_ctx = _build_plot_context(FlatTerrain(), _tall_samples())
    climb_apex_over_target, climb_projected_dx = _ballistic_projection_series(
        ctx=climb_ctx,
        target={"x": 120.0, "y": 0.0},
    )
    descend_ctx = _build_plot_context(FlatTerrain(), _samples())
    descend_apex_over_target, descend_projected_dx = _ballistic_projection_series(
        ctx=descend_ctx,
        target={"x": 120.0, "y": 0.0},
    )

    assert len(climb_apex_over_target) == len(climb_ctx.sample_times)
    assert len(climb_projected_dx) == len(climb_ctx.sample_times)
    assert len(descend_apex_over_target) == len(descend_ctx.sample_times)
    assert len(descend_projected_dx) == len(descend_ctx.sample_times)
    assert climb_apex_over_target[0] > climb_ctx.ys[0]
    assert descend_apex_over_target[-1] == descend_ctx.ys[-1]


def test_compute_figure_size_keeps_spatial_minimums_for_colorbar_space() -> None:
    wide_w, wide_h = _compute_figure_size(640.0, 160.0, layout="single")
    tall_w, tall_h = _compute_figure_size(160.0, 640.0, layout="all", arrangement="columns")
    assert wide_h >= 6.3
    assert tall_w >= 15.0
    assert tall_h >= 18.8


def test_save_trajectory_plots_tall_combined_stays_close_to_square(tmp_path: Path) -> None:
    out_dir = tmp_path / "tall_combined"
    result = save_trajectory_plots(
        FlatTerrain(),
        _tall_samples(),
        mode="all",
        output_profile="combined",
        out_dir=str(out_dir),
        max_side_px=1200,
        selector_tag="climb_slope_high_0",
    )

    image = mpimg.imread(Path(result["plot_path"]))
    assert image.shape[1] / image.shape[0] > 0.84


def test_save_trajectory_plots_tall_split_does_not_become_overly_wide(tmp_path: Path) -> None:
    out_dir = tmp_path / "tall_split"
    result = save_trajectory_plots(
        FlatTerrain(),
        _tall_samples(),
        mode="speed",
        output_profile="split",
        out_dir=str(out_dir),
        max_side_px=1200,
        selector_tag="climb_slope_high_0",
    )

    image = mpimg.imread(Path(result["plot_path"]))
    assert image.shape[1] / image.shape[0] < 1.3


def test_save_trajectory_plots_shallow_split_is_not_extremely_flat(tmp_path: Path) -> None:
    out_dir = tmp_path / "shallow_split"
    result = save_trajectory_plots(
        FlatTerrain(),
        _shallow_samples(),
        mode="speed",
        output_profile="split",
        out_dir=str(out_dir),
        max_side_px=1200,
        selector_tag="launch_near_0",
    )

    image = mpimg.imread(Path(result["plot_path"]))
    assert image.shape[1] / image.shape[0] < 2.6


def test_sorted_gate_events_prefers_short_labels_and_time_order() -> None:
    events = [
        {"name": "terminal_entry", "time_s": 3.2, "label": "flare green dx=4.0"},
        {"name": "setup_gate", "time_s": 1.1, "label": "setup gate"},
        {"name": "success", "time_s": 4.0, "label": "landed"},
    ]

    assert _sorted_gate_events(events) == [
        ("setup_gate", 1.1, "setup gate"),
        ("terminal_entry", 3.2, "flare green dx=4.0"),
    ]


def test_plotter_finalize_appends_landing_outcome_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    lander = Lander(start_pos=Vector2(0.0, 40.0))
    plotter = Plotter(FlatTerrain(), lander, enabled=True, mode="speed", output_profile="combined")
    plotter.set_selector_tag("landing_case")
    plotter.seed_initial_sample()

    transform = lander.get_component(Transform)
    state = lander.get_component(LanderState)
    assert transform is not None
    assert state is not None
    transform.pos = Vector2(24.0, 0.0)
    state.state = FlightState.LANDED

    result = plotter.finalize()
    manifest = Path(result["plot_manifest_path"])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    success_events = [event for event in payload["events"] if event.get("name") == "success"]

    assert len(success_events) == 1
    assert success_events[0]["label"] == "landed"
    assert success_events[0]["x"] == 24.0
    assert success_events[0]["y"] == 0.0
