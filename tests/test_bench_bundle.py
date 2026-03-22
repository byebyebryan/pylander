from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(rel: str) -> Path:
    return (REPO_ROOT / rel).resolve()


bench_bundle = _load_module(
    "bench_bundle_script",
    _script("skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py"),
)


def test_parse_section_reads_key_value_block() -> None:
    output = """
# candidate
commit=8b2f6cd
json=/tmp/candidate.json
csv=/tmp/candidate.csv
meta=/tmp/candidate.meta.json
cached=False

# policy
included_levels=boost,plunge,terminal
"""
    section = bench_bundle._parse_section(output, "candidate")
    assert section == {
        "commit": "8b2f6cd",
        "json": "/tmp/candidate.json",
        "csv": "/tmp/candidate.csv",
        "meta": "/tmp/candidate.meta.json",
        "cached": "False",
    }


def test_discover_viewer_hostname_prefers_lan(monkeypatch) -> None:
    monkeypatch.setattr(bench_bundle.socket, "gethostname", lambda: "starship")
    monkeypatch.setattr(bench_bundle.socket, "getfqdn", lambda: "starship")

    def _fake_gethostbyname(host: str) -> str:
        if host == "starship.lan":
            return "192.168.1.212"
        raise OSError(host)

    monkeypatch.setattr(bench_bundle.socket, "gethostbyname", _fake_gethostbyname)
    monkeypatch.setattr(bench_bundle, "_local_ip", lambda: "192.168.1.212")

    assert bench_bundle._discover_viewer_hostname() == "starship.lan"


def test_scenario_plot_selectors_prefers_failed_seed_then_lowest_seed() -> None:
    selectors = bench_bundle._scenario_plot_selectors(
        {
            "records": [
                {
                    "level": "boost",
                    "scenario": "climb:high:full",
                    "seed": 3,
                    "success": True,
                    "state": "landed",
                },
                {
                    "level": "boost",
                    "scenario": "climb:high:full",
                    "seed": 1,
                    "success": False,
                    "state": "crashed",
                },
                {
                    "level": "terminal",
                    "scenario": "normal:mid",
                    "seed": 2,
                    "success": True,
                    "state": "landed",
                },
                {
                    "level": "terminal",
                    "scenario": "normal:mid",
                    "seed": 0,
                    "success": True,
                    "state": "landed",
                },
            ]
        }
    )

    assert selectors == [
        "boost:climb:high:full:1",
        "terminal:normal:mid:0",
    ]


def test_plot_pack_command_uses_focus_mode_for_per_scenario_scope(tmp_path: Path) -> None:
    args = bench_bundle.argparse.Namespace(
        bot="pdg",
        top_plots=8,
        plot_scope="per-scenario",
        plot_mode="all",
        plot_output="both",
        plot_max_side_px=1800,
        plot_workers=0,
    )
    cmd = bench_bundle._plot_pack_command(
        benchmark_json=tmp_path / "candidate.json",
        candidate_payload={
            "records": [
                {
                    "level": "plunge",
                    "scenario": "high:full",
                    "seed": 0,
                    "success": True,
                    "state": "landed",
                },
                {
                    "level": "terminal",
                    "scenario": "normal:mid",
                    "seed": 0,
                    "success": True,
                    "state": "landed",
                },
            ]
        },
        compare_json=None,
        bundle_plot_manifest=tmp_path / "plot_pack.json",
        args=args,
    )

    assert cmd[cmd.index("--mode") + 1] == "focus"
    assert cmd[cmd.index("--top-n") + 1] == "2"
    selectors_idx = cmd.index("--selectors") + 1
    assert cmd[selectors_idx:] == [
        "plunge:high:full:0",
        "terminal:normal:mid:0",
    ]


def test_all_run_plot_selectors_order_by_scenario_then_seed() -> None:
    selectors = bench_bundle._all_run_plot_selectors(
        {
            "records": [
                {
                    "level": "terminal",
                    "scenario": "normal:mid",
                    "seed": 2,
                    "success": True,
                    "state": "landed",
                },
                {
                    "level": "boost",
                    "scenario": "climb:high:full",
                    "seed": 1,
                    "success": False,
                    "state": "crashed",
                },
                {
                    "level": "terminal",
                    "scenario": "normal:mid",
                    "seed": 0,
                    "success": True,
                    "state": "landed",
                },
            ]
        }
    )

    assert selectors == [
        "boost:climb:high:full:1",
        "terminal:normal:mid:0",
        "terminal:normal:mid:2",
    ]


def test_plot_pack_command_uses_focus_mode_for_per_run_scope(tmp_path: Path) -> None:
    args = bench_bundle.argparse.Namespace(
        bot="pdg",
        top_plots=8,
        plot_scope="per-run",
        plot_mode="all",
        plot_output="split",
        plot_max_side_px=1800,
        plot_workers=0,
    )
    cmd = bench_bundle._plot_pack_command(
        benchmark_json=tmp_path / "candidate.json",
        candidate_payload={
            "records": [
                {
                    "level": "plunge",
                    "scenario": "high:full",
                    "seed": 1,
                    "success": True,
                    "state": "landed",
                },
                {
                    "level": "plunge",
                    "scenario": "high:full",
                    "seed": 0,
                    "success": True,
                    "state": "landed",
                },
            ]
        },
        compare_json=None,
        bundle_plot_manifest=tmp_path / "plot_pack.json",
        args=args,
    )

    assert cmd[cmd.index("--mode") + 1] == "focus"
    assert cmd[cmd.index("--top-n") + 1] == "2"
    assert cmd[cmd.index("--plot-output") + 1] == "split"
    selectors_idx = cmd.index("--selectors") + 1
    assert cmd[selectors_idx:] == [
        "plunge:high:full:0",
        "plunge:high:full:1",
    ]


def test_write_bundle_files_renders_relative_links_and_latest_redirect(tmp_path: Path) -> None:
    outputs_root = tmp_path / "outputs"
    (outputs_root / "benchmarks" / "head").mkdir(parents=True)
    (outputs_root / "plots" / "overview").mkdir(parents=True)
    (outputs_root / "plots" / "case_a").mkdir(parents=True)

    candidate_json = outputs_root / "benchmarks" / "head" / "full_pack.json"
    candidate_csv = outputs_root / "benchmarks" / "head" / "full_pack.csv"
    candidate_meta = outputs_root / "benchmarks" / "head" / "full_pack.meta.json"
    compare_json = outputs_root / "benchmarks" / "head" / "full_pack.compare.json"
    plot_pack_manifest = outputs_root / "viewer" / "bundles" / "bundle_x" / "plot_pack.json"
    overview_png = outputs_root / "plots" / "overview" / "case_a.png"
    bundle_manifest = outputs_root / "plots" / "case_a" / "manifest.json"
    spatial_traj = outputs_root / "plots" / "case_a" / "spatial_trajectory_comparison.png"
    spatial_speed = outputs_root / "plots" / "case_a" / "spatial_speed.png"

    candidate_payload = {
        "summary": {
            "runs": 10,
            "successes": 9,
            "crashed": 1,
            "success_rate": 0.9,
            "efficiency_success": {
                "fuel_consumed": {"mean": 12.5},
                "time": {"mean": 8.75},
                "bot_profile_total_ms_per_tick": {"mean": 1.25},
                "bot_profile_total_ms_per_tick_p99": {"mean": 4.5},
            },
            "by_selector": {
                "boost:climb:high:full": {
                    "runs": 10,
                    "successes": 9,
                    "crashed": 1,
                    "success_rate": 0.9,
                    "efficiency_success": {
                        "fuel_consumed": {"mean": 21.0},
                        "time": {"mean": 14.0},
                        "bot_profile_total_ms_per_tick": {"mean": 1.75},
                    },
                }
            },
        },
        "records": [
            {
                "level": "boost",
                "scenario": "climb:high:full",
                "seed": 0,
                "success": False,
                "state": "crashed",
                "failure_mode": "crashed",
                "fuel_consumed": 10.0,
                "time": 12.1,
            }
        ],
    }
    compare_payload = {
        "notable_regression": True,
        "global": {
            "crash": {
                "new_crashes": [
                    {
                        "level": "boost",
                        "scenario": "climb:high:full",
                        "seed": 0,
                        "candidate_failure_mode": "crashed",
                        "baseline_state": "landed",
                    }
                ]
            },
            "worst_scenarios": [
                {
                    "scenario": "boost:climb:high:full",
                    "delta_success_rate": -1.0,
                    "delta_fuel_mean": 4.2,
                    "fuel_basis": "success",
                }
            ],
            "compute": {},
        },
    }
    plot_pack_payload = {
        "cases": [
            {
                "selector": "boost:climb:high:full:0",
                "severity": "critical",
                "reason": "crash",
                "command": ["uv", "run", "python", "main.py", "plot", "boost:climb:high:full:0"],
                "plot_paths": [
                    "outputs/plots/overview/case_a.png",
                    "outputs/plots/case_a/spatial_speed.png",
                ],
                "plot_manifest_path": "outputs/plots/case_a/manifest.json",
                "plot_bundle_dir": "outputs/plots/case_a",
            }
        ]
    }

    candidate_json.write_text(json.dumps(candidate_payload), encoding="utf-8")
    candidate_csv.write_text("selector\nboost:climb:high:full\n", encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")
    compare_json.write_text(json.dumps(compare_payload), encoding="utf-8")
    overview_png.write_bytes(b"png")
    spatial_traj.write_bytes(b"png")
    spatial_speed.write_bytes(b"png")
    bundle_manifest.write_text(
        json.dumps(
            {
                "events": [{"name": "success", "label": "landed", "time_s": 12.1, "x": 0.0, "y": 4.0}],
                "plots": [
                    {"filename": "case_a.png", "path": "outputs/plots/overview/case_a.png"},
                    {"filename": "spatial_trajectory_comparison.png", "path": "outputs/plots/case_a/spatial_trajectory_comparison.png"},
                    {"filename": "spatial_speed.png", "path": "outputs/plots/case_a/spatial_speed.png"},
                ],
                "target": {"x": 0.0, "y": 0.0, "label": "landing target", "size": 110.0},
            }
        ),
        encoding="utf-8",
    )

    bundle = bench_bundle._bundle_payload(
        bundle_id="bundle_x",
        created_at_utc="2026-03-21T18:00:00+00:00",
        benchmark_cmd=["uv", "run", "python", "skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py"],
        benchmark_exit_code=1,
        benchmark_wall_clock_s=12.5,
        candidate_json_path=candidate_json,
        candidate_csv_path=candidate_csv,
        candidate_meta_path=candidate_meta,
        candidate_payload=candidate_payload,
        candidate_cached="False",
        compare_path=compare_json,
        compare_payload=compare_payload,
        plot_pack_cmd=["uv", "run", "python", "skills/pylander-plot-runner/scripts/build_plot_pack.py"],
        plot_pack_exit_code=0,
        plot_pack_wall_clock_s=23.75,
        plot_pack_path=plot_pack_manifest,
        plot_pack_payload=plot_pack_payload,
        plot_scope="per-scenario",
        outputs_root=outputs_root,
    )

    html_path, bundle_json_path, latest_path = bench_bundle._write_bundle_files(
        bundle,
        outputs_root=outputs_root,
    )

    html_payload = html_path.read_text(encoding="utf-8")
    latest_payload = latest_path.read_text(encoding="utf-8")
    bundle_json_payload = json.loads(bundle_json_path.read_text(encoding="utf-8"))
    detail_html = (
        outputs_root / "viewer" / "bundles" / "bundle_x" / "runs" / "boost_climb_high_full_0.html"
    ).read_text(encoding="utf-8")

    assert "Quick Summary" in html_payload
    assert "Wall clock:" in html_payload
    assert "Show commands" in html_payload
    assert "scenario-table" in html_payload
    assert "scenario-row" in html_payload
    assert "seed-row" in html_payload
    assert "boost:climb:high:full" in html_payload
    assert "runs/boost_climb_high_full_0.html" in html_payload
    assert "../../../plots/case_a/spatial_trajectory_comparison.png" in html_payload
    assert "../../../benchmarks/head/full_pack.json" in html_payload
    assert "notable_regression=True" in html_payload
    assert "../bundles/bundle_x/index.html" in latest_payload
    assert bundle_json_payload["plot_pack"]["manifest_path"] == "viewer/bundles/bundle_x/plot_pack.json"
    assert bundle_json_payload["plot_pack"]["selection_scope"] == "per-scenario"
    assert bundle_json_payload["timing"]["benchmark_wall_clock_s"] == 12.5
    assert bundle_json_payload["timing"]["plot_pack_wall_clock_s"] == 23.75
    assert bundle_json_payload["timing"]["bundle_render_wall_clock_s"] is not None
    assert bundle_json_payload["timing"]["total_wall_clock_s"] is not None
    assert "Pylander Run Detail" in detail_html
    assert "plot-strip" in detail_html
    assert "../../../../plots/case_a/spatial_trajectory_comparison.png" in detail_html
    assert "../../../../plots/case_a/spatial_speed.png" in detail_html
    assert "../../../../plots/overview/case_a.png" not in detail_html
