from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import app.output_viewer as output_viewer
import app.trace_bundle as trace_bundle
import utils.traceviewer as traceviewer


def test_parse_section_reads_key_value_block() -> None:
    output = """
# candidate
commit=8b2f6cd
json=/tmp/candidate.tracepack.json
meta=/tmp/candidate.meta.json
cached=False
"""
    section = trace_bundle._parse_section(output, "candidate")
    assert section == {
        "commit": "8b2f6cd",
        "json": "/tmp/candidate.tracepack.json",
        "meta": "/tmp/candidate.meta.json",
        "cached": "False",
    }


def test_benchmark_command_uses_app_module_entrypoint() -> None:
    cmd = trace_bundle._benchmark_command(
        argparse.Namespace(
            mode="quick",
            bot="pdg",
            results_dir="outputs/benchmarks",
            crash_detail_limit=8,
            seed_spec=None,
            selectors=[],
            exclude_levels=[],
            observe_only_levels=[],
            bot_config=None,
            bot_profile=True,
            bot_profile_interval_s=None,
            bot_profile_logs=False,
            baseline_ref=None,
            no_reuse=False,
        )
    )

    assert cmd[:5] == ["uv", "run", "python", "-m", "app.run_cached_benchmark"]


def test_viewer_base_url_requires_running_server_without_explicit_base_url() -> None:
    assert (
        trace_bundle._viewer_base_url(
            viewer_base_url=None,
            viewer_hostname="starship.lan",
            server_port=8765,
            server_status="disabled",
        )
        is None
    )
    assert (
        trace_bundle._viewer_base_url(
            viewer_base_url=None,
            viewer_hostname="starship.lan",
            server_port=8765,
            server_status="reused",
        )
        == "http://starship.lan:8765"
    )
    assert (
        trace_bundle._viewer_base_url(
            viewer_base_url="http://example.test/base/",
            viewer_hostname="starship.lan",
            server_port=8765,
            server_status="disabled",
        )
        == "http://example.test/base"
    )


def test_discover_viewer_hostname_prefers_lan(monkeypatch) -> None:
    monkeypatch.setattr(output_viewer.socket, "gethostname", lambda: "starship")
    monkeypatch.setattr(output_viewer.socket, "getfqdn", lambda: "starship")

    def _fake_gethostbyname(host: str) -> str:
        if host == "starship.lan":
            return "192.168.1.212"
        raise OSError(host)

    monkeypatch.setattr(output_viewer.socket, "gethostbyname", _fake_gethostbyname)
    monkeypatch.setattr(output_viewer, "local_ip", lambda: "192.168.1.212")

    assert output_viewer.discover_viewer_hostname() == "starship.lan"


def test_traceviewer_uses_pinned_plotly_cdn() -> None:
    viewer_assets = traceviewer.ensure_viewer_assets(Path("/tmp/outputs"))
    assert viewer_assets == {
        "plotly_href": "https://cdn.plot.ly/plotly-basic-2.35.2.min.js"
    }


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
    intent_json = outputs_root / "benchmarks" / "head" / "full_pack.tracepack.intent.json"
    analysis_json = outputs_root / "benchmarks" / "head" / "full_pack.tracepack.analysis.json"
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
    intent_payload = {
        "schema": "pylander.benchmark.intent.v1",
        "goal_summary": "Check boost climb tuning against the last behavior change",
        "request_source": "mixed",
        "conversation_context": ["User asked for a full regression pass after boost tuning."],
        "repo_context": {
            "changed_files": ["bots/pdg.py", "README.md"],
            "touched_areas": ["bot_logic", "docs"],
        },
        "baseline_plan": {
            "strategy": "auto",
            "requested_ref": "auto",
            "resolved_ref": "8b2f6cd",
            "skipped_commits": [
                {
                    "commit": "aa11bb2",
                    "skip_reason": "changed files are limited to docs, skills, tests, or benchmark tooling",
                    "subject": "docs: clarify benchmark workflow",
                }
            ],
        },
    }
    analysis_payload = {
        "schema": "pylander.benchmark.analysis.v1",
        "verdict": "regression",
        "summary": "Boost climb success rate regressed with one new crash.",
        "measured_evidence": [
            "candidate success_rate=0.900",
            "global delta success_rate=-1.000",
        ],
        "likely_causes": [
            "Changed files include bot logic, so guidance behavior is the most likely cause."
        ],
        "confidence": "high",
        "follow_ups": [
            "uv run python main.py plot boost:climb:high:full:0 --bot pdg"
        ],
    }

    candidate_json.write_text(json.dumps(candidate_payload), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")
    compare_json.write_text(json.dumps(compare_payload), encoding="utf-8")
    intent_json.write_text(json.dumps(intent_payload), encoding="utf-8")
    analysis_json.write_text(json.dumps(analysis_payload), encoding="utf-8")

    bundle = trace_bundle._bundle_payload(
        bundle_id="bundle_x",
        created_at_utc="2026-03-21T18:00:00+00:00",
        benchmark_cmd=[
            "uv",
            "run",
            "python",
            "-m",
            "app.run_cached_benchmark",
        ],
        benchmark_exit_code=1,
        benchmark_wall_clock_s=12.5,
        candidate_json_path=candidate_json,
        candidate_meta_path=candidate_meta,
        candidate_payload=candidate_payload,
        candidate_cached="False",
        compare_path=compare_json,
        compare_payload=compare_payload,
        intent_path=intent_json,
        intent_payload=intent_payload,
        analysis_path=analysis_json,
        analysis_payload=analysis_payload,
        outputs_root=outputs_root,
        viewer_assets={"plotly_href": "https://cdn.plot.ly/plotly-basic-2.35.2.min.js"},
    )

    html_path, bundle_json_path, latest_path = trace_bundle._write_bundle_files(
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
    assert "Context" in html_payload
    assert "Baseline" in html_payload
    assert "Outcome" in html_payload
    assert "Analysis" in html_payload
    assert "intent json" in html_payload
    assert "analysis json" in html_payload
    assert "Check boost climb tuning against the last behavior change" in html_payload
    assert "Boost climb success rate regressed with one new crash." in html_payload
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
        bundle_json_payload["viewer_assets"]["plotly_href"]
        == "https://cdn.plot.ly/plotly-basic-2.35.2.min.js"
    )
    assert bundle_json_payload["intent"]["baseline_resolved_ref"] == "8b2f6cd"
    assert bundle_json_payload["analysis"]["verdict"] == "regression"
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
    assert 'https://cdn.plot.ly/plotly-basic-2.35.2.min.js' in detail_html
    match = re.search(
        r'<script id="trace-plot-json" type="application/json">(.*?)</script>',
        detail_html,
        re.S,
    )
    assert match is not None
    detail_payload = json.loads(match.group(1))
    assert detail_payload["samples"]["x"] == [-20.0, -5.0, 4.0]

    rendered = trace_bundle.render_bundle(
        candidate_json_path=candidate_json,
        candidate_meta_path=candidate_meta,
        compare_path=compare_json,
        intent_path=None,
        analysis_path=None,
        benchmark_cmd=[
            "uv",
            "run",
            "python",
            "-m",
            "app.run_cached_benchmark",
            "--mode",
            "full",
        ],
        benchmark_exit_code=1,
        benchmark_wall_clock_s=12.5,
        outputs_root=outputs_root,
        bundle_id="bundle_report_x",
        candidate_cached="True",
    )
    rendered_payload = json.loads(
        rendered.bundle_json_path.read_text(encoding="utf-8")
    )
    assert rendered.bundle_page_path.exists()
    assert (
        rendered_payload["compare"]["json_path"]
        == "benchmarks/head/full_pack.compare.json"
    )
    assert rendered_payload["benchmark"]["candidate"]["cached"] == "True"
    assert rendered_payload["intent"]["goal_summary"].startswith("Check boost climb")
    assert rendered_payload["analysis"]["verdict"] == "regression"
