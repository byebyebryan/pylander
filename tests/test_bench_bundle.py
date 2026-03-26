from __future__ import annotations

import importlib.util
import json
import re
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
    _script(".agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py"),
)


def test_parse_section_reads_key_value_block() -> None:
    output = """
# candidate
commit=8b2f6cd
json=/tmp/candidate.tracepack.json
meta=/tmp/candidate.meta.json
cached=False
"""
    section = bench_bundle._parse_section(output, "candidate")
    assert section == {
        "commit": "8b2f6cd",
        "json": "/tmp/candidate.tracepack.json",
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


def test_write_bundle_files_renders_tracepack_report(tmp_path: Path) -> None:
    outputs_root = tmp_path / "outputs"
    trace_root = outputs_root / "benchmarks" / "head" / "full_pack.tracepack"
    trace_dir = trace_root / "traces"
    preview_dir = trace_root / "previews"
    trace_dir.mkdir(parents=True)
    preview_dir.mkdir(parents=True)
    (outputs_root / "benchmarks" / "head").mkdir(parents=True, exist_ok=True)

    candidate_json = outputs_root / "benchmarks" / "head" / "full_pack.tracepack.json"
    candidate_meta = outputs_root / "benchmarks" / "head" / "full_pack.meta.json"
    compare_json = outputs_root / "benchmarks" / "head" / "full_pack.compare.json"
    trace_path = trace_dir / "boost_climb_high_full_0.trace.json"
    preview_path = preview_dir / "boost_climb_high_full_0.png"

    trace_payload = {
        "schema": "pylander.run_trace.v1",
        "schema_version": 1,
        "plot": {
            "terrain": {"xs": [-40.0, 0.0, 40.0], "ys": [0.0, 0.0, 0.0]},
            "target": {"x": 0.0, "y": 0.0, "label": "landing target", "size": 110.0},
            "events": [
                {
                    "name": "crash",
                    "label": "crashed",
                    "time_s": 12.1,
                    "x": 4.0,
                    "y": 1.5,
                }
            ],
            "bounds": {"min_x": -40.0, "max_x": 40.0, "lower_y": -5.0, "upper_y": 60.0},
            "samples": {
                "time_s": [0.0, 1.0, 2.0],
                "x": [-20.0, -5.0, 4.0],
                "y": [48.0, 22.0, 1.5],
                "speed": [14.0, 18.0, 35.0],
                "thrust": [0.8, 0.7, 0.2],
                "angle": [0.0, -8.0, -12.0],
                "vx": [6.0, 8.0, 12.0],
                "vy": [-20.0, -18.0, -32.0],
            },
            "ballistic_curve": {"xs": [4.0, 6.0, 8.0], "ys": [1.5, 0.8, 0.0]},
            "reference_curve": {
                "xs": [-20.0, -8.0, 0.0],
                "ys": [48.0, 30.0, 0.0],
                "apex_y": 52.0,
            },
        },
    }
    trace_path.write_text(json.dumps(trace_payload), encoding="utf-8")
    preview_path.write_bytes(b"png")

    candidate_payload = {
        "schema": "pylander.tracepack.v1",
        "schema_version": 2,
        "trace_sample_period_s": 0.25,
        "trace_root_path": str(trace_root),
        "trace_root_rel": "benchmarks/head/full_pack.tracepack",
        "summary": {
            "runs": 10,
            "successes": 9,
            "crashed": 1,
            "success_rate": 0.9,
            "efficiency_all": {
                "fuel_consumed": {"mean": 13.5},
                "time": {"mean": 9.25},
                "bot_profile_total_ms_per_tick": {"mean": 1.5},
                "bot_profile_total_ms_per_tick_p90": {"mean": 3.25},
                "bot_profile_total_ms_per_tick_p99": {"mean": 5.0},
            },
            "efficiency_success": {
                "fuel_consumed": {"mean": 12.5},
                "time": {"mean": 8.75},
                "bot_profile_total_ms_per_tick": {"mean": 1.25},
                "bot_profile_total_ms_per_tick_p90": {"mean": 3.0},
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
                "bot": "pdg",
                "level": "boost",
                "scenario": "climb:high:full",
                "seed": 0,
                "success": False,
                "state": "crashed",
                "failure_mode": "crashed",
                "fuel_consumed": 10.0,
                "time": 12.1,
                "run_key": "boost:climb:high:full:0",
                "run_instance_id": 1,
                "trace_path": str(trace_path),
                "trace_rel_path": "benchmarks/head/full_pack.tracepack/traces/boost_climb_high_full_0.trace.json",
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": "benchmarks/head/full_pack.tracepack/previews/boost_climb_high_full_0.png",
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

    candidate_json.write_text(json.dumps(candidate_payload), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")
    compare_json.write_text(json.dumps(compare_payload), encoding="utf-8")

    bundle = bench_bundle._bundle_payload(
        bundle_id="bundle_x",
        created_at_utc="2026-03-21T18:00:00+00:00",
        benchmark_cmd=[
            "uv",
            "run",
            "python",
            ".agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
        ],
        benchmark_exit_code=1,
        benchmark_wall_clock_s=12.5,
        candidate_json_path=candidate_json,
        candidate_meta_path=candidate_meta,
        candidate_payload=candidate_payload,
        candidate_cached="False",
        compare_path=compare_json,
        compare_payload=compare_payload,
        outputs_root=outputs_root,
        viewer_assets={"plotly_rel": "viewer/assets/plotly-basic-2.35.2.min.js"},
    )

    html_path, bundle_json_path, latest_path = bench_bundle._write_bundle_files(
        bundle,
        outputs_root=outputs_root,
    )

    html_payload = html_path.read_text(encoding="utf-8")
    latest_payload = latest_path.read_text(encoding="utf-8")
    bundle_json_payload = json.loads(bundle_json_path.read_text(encoding="utf-8"))
    detail_html = (
        outputs_root
        / "viewer"
        / "bundles"
        / "bundle_x"
        / "runs"
        / "boost_climb_high_full_0.html"
    ).read_text(encoding="utf-8")

    assert "Bench Id" in html_payload
    assert "Wall Clock Total" in html_payload
    assert "Fuel Mean Success" in html_payload
    assert "Show commands" in html_payload
    assert "Expand All" in html_payload
    assert "Collapse All" in html_payload
    assert "<th>Details</th>" in html_payload
    assert "boost:climb:high:full" in html_payload
    assert (
        "../../../benchmarks/head/full_pack.tracepack/previews/boost_climb_high_full_0.png"
        in html_payload
    )
    assert "plot pack" not in html_payload.lower()
    assert "Bench Id" in latest_payload
    assert "latest page" in latest_payload
    assert "../bundles/bundle_x/runs/boost_climb_high_full_0.html" in latest_payload
    assert (
        bundle_json_payload["benchmark"]["candidate"]["schema"]
        == "pylander.tracepack.v1"
    )
    assert bundle_json_payload["benchmark"]["candidate"]["trace_root_path"] == str(
        trace_root
    )
    assert (
        bundle_json_payload["viewer_assets"]["plotly_rel"]
        == "viewer/assets/plotly-basic-2.35.2.min.js"
    )
    assert bundle_json_payload["timing"]["benchmark_wall_clock_s"] == 12.5
    assert bundle_json_payload["timing"]["bundle_render_wall_clock_s"] is not None
    assert bundle_json_payload["timing"]["total_wall_clock_s"] is not None
    assert "Interactive Detail" in detail_html
    assert "chart-spatial" in detail_html
    assert "chart-metrics" in detail_html
    assert "chart-speed-spatial" not in detail_html
    assert "chart-thrust-spatial" not in detail_html
    assert 'data-mode="plain"' in detail_html
    assert 'data-mode="speed"' in detail_html
    assert 'data-mode="thrust"' in detail_html
    assert 'data-mode="vectors"' in detail_html
    assert ">Velocity<" in detail_html
    assert ">Thrust<" in detail_html
    assert ">Vectors<" in detail_html
    assert 'spatialElement.on("plotly_hover"' in detail_html
    assert (
        'spatialElement.addEventListener("mouseleave", () => updateThrustVector(null));'
        in detail_html
    )
    assert "const buildHoverCarrier = () => {" in detail_html
    assert "const hoverSubdivisionCount = 6;" in detail_html
    assert "const buildVectorModeAnnotations = (intervalS) => {" in detail_html
    assert "const vectorModeIntervalS = 1.0;" in detail_html
    assert 'mode: "lines"' in detail_html
    assert (
        'const hoverCarrierIndex = spatialTraces.findIndex((trace) => trace.name === "trajectory hover");'
        in detail_html
    )
    assert (
        'const eventTraceIndex = spatialTraces.findIndex((trace) => trace.name === "events");'
        in detail_html
    )
    assert "const applySpatialMode = (mode, hoverIndex = null) => {" in detail_html
    assert 'if (currentSpatialMode !== "thrust") return;' in detail_html
    assert (
        "points.some((point) => point.curveNumber === eventTraceIndex)" in detail_html
    )
    assert (
        "requestAnimationFrame(() => Plotly.Fx.unhover(spatialElement));" in detail_html
    )
    assert "arrowhead: 3" in detail_html
    assert "vectorModeAnnotations" in detail_html
    assert "thrustExtent.min" in detail_html
    assert "shapes: eventGuideShapes" in detail_html
    assert 'hoverinfo: "skip"' in detail_html
    assert 'xaxis: {title: "", domain: [0.0, 0.93]}' in detail_html
    assert 'yaxis: {title: "", scaleanchor: "x", scaleratio: 1}' in detail_html
    assert "x: 0.955," in detail_html
    assert 'name: "velocity"' in detail_html
    assert 'name: "vx"' in detail_html
    assert 'visible: "legendonly"' in detail_html
    assert 'return {symbol: "star", color: "#2f9e44"};' in detail_html
    assert 'return {symbol: "circle", color: "#5b73c6"};' in detail_html
    assert (
        'return eventName === "success" || eventName === "crash" ? 16.5 : 15;'
        in detail_html
    )
    assert "trace json" in detail_html
    assert "plot manifest" not in detail_html
    assert "plotly-basic-2.35.2.min.js" in detail_html
    match = re.search(
        r'<script id="trace-plot-json" type="application/json">(.*?)</script>',
        detail_html,
        re.S,
    )
    assert match is not None
    detail_payload = json.loads(match.group(1))
    assert detail_payload["samples"]["x"] == [-20.0, -5.0, 4.0]
