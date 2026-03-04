from __future__ import annotations

import json
from pathlib import Path

import matplotlib.image as mpimg

from utils.plot import save_trajectory_plots


class _FlatTerrain:
    def get_resolution(self, lod: int) -> float:
        _ = lod
        return 10.0

    def __call__(self, x: float, lod: int = 0) -> float:
        _ = x, lod
        return 0.0


def _samples() -> list[tuple[float, float, float, float, float, float, float, float]]:
    return [
        (0.0, 120.0, 15.0, 0.2, 0.0, 0.0, 0.0, -12.0),
        (60.0, 100.0, 16.0, 0.4, 0.1, 0.5, 8.0, -13.0),
        (120.0, 70.0, 18.0, 0.7, 0.2, 1.0, 10.0, -15.0),
        (170.0, 30.0, 22.0, 0.1, 0.4, 1.5, 14.0, -20.0),
    ]


def test_save_trajectory_plots_combined_writes_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "combined"
    result = save_trajectory_plots(
        _FlatTerrain(),
        _samples(),
        mode="all",
        output_profile="combined",
        out_dir=str(out_dir),
        max_side_px=1200,
        selector_tag="launch_far_0",
    )

    assert len(result.get("plot_paths") or []) == 1
    assert Path(result["plot_path"]).exists()
    manifest = Path(result["plot_manifest_path"])
    assert manifest.exists()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["plot_output"] == "combined"
    assert payload["plot_count"] == 1


def test_save_trajectory_plots_split_all_writes_expected_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "split"
    result = save_trajectory_plots(
        _FlatTerrain(),
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
        "spatial_thrust.png",
        "spatial_thrust_vectors.png",
        "timeseries_speed_thrust.png",
        "timeseries_hv_speed.png",
    }.issubset(names)
    assert Path(result["plot_manifest_path"]).exists()


def test_save_trajectory_plots_respects_max_side_px(tmp_path: Path) -> None:
    out_dir = tmp_path / "capped"
    result = save_trajectory_plots(
        _FlatTerrain(),
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
        _FlatTerrain(),
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
