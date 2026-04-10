from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import app.output_viewer as output_viewer
import app.trace_bundle as trace_bundle
import tooling.traceviewer as traceviewer


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
    baseline_root = outputs_root / "benchmarks" / "base" / "full_pack.tracepack"
    baseline_trace_dir = baseline_root / "traces"
    baseline_preview_dir = baseline_root / "previews"
    baseline_trace_dir.mkdir(parents=True)
    baseline_preview_dir.mkdir(parents=True)
    baseline_json = outputs_root / "benchmarks" / "base" / "full_pack.tracepack.json"
    baseline_meta = outputs_root / "benchmarks" / "base" / "full_pack.meta.json"
    compare_json = outputs_root / "benchmarks" / "head" / "full_pack.compare.json"
    intent_json = (
        outputs_root / "benchmarks" / "head" / "full_pack.tracepack.intent.json"
    )
    analysis_json = (
        outputs_root / "benchmarks" / "head" / "full_pack.tracepack.analysis.json"
    )
    trace_path = trace_dir / "boost_climb_high_full_0.trace.json"
    preview_path = preview_dir / "boost_climb_high_full_0.png"
    baseline_trace_path = baseline_trace_dir / "boost_climb_high_full_0.trace.json"
    baseline_preview_path = baseline_preview_dir / "boost_climb_high_full_0.png"

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
                "kind": "ballistic_vx_adjusted",
                "label": "ballistic ref (vx adjusted)",
            },
        },
    }
    trace_path.write_text(json.dumps(trace_payload), encoding="utf-8")
    preview_path.write_bytes(b"png")
    baseline_trace_path.write_text(json.dumps(trace_payload), encoding="utf-8")
    baseline_preview_path.write_bytes(b"png")

    candidate_payload = {
        "schema": "pylander.tracepack.v1",
        "schema_version": 2,
        "benchmark_wall_clock_s": 12.5,
        "trace_sample_period_s": 0.25,
        "trace_root_path": str(trace_root),
        "trace_root_rel": "benchmarks/head/full_pack.tracepack",
        "summary": {
            "runs": 10,
            "successes": 9,
            "crashed": 1,
            "success_rate": 0.9,
            "efficiency_all": {
                "fuel_consumed": {"count": 10, "mean": 13.5, "stddev": 2.0},
                "time": {"count": 10, "mean": 9.25, "stddev": 0.8},
                "bot_profile_total_ms_per_tick": {"count": 10, "mean": 1.5},
                "bot_profile_total_ms_per_tick_p90": {"count": 10, "mean": 3.25},
                "bot_profile_total_ms_per_tick_p99": {"count": 10, "mean": 5.0},
            },
            "efficiency_success": {
                "fuel_consumed": {"count": 9, "mean": 12.5, "stddev": 1.75},
                "time": {"count": 9, "mean": 8.75, "stddev": 0.65},
                "bot_profile_total_ms_per_tick": {"count": 9, "mean": 1.25},
                "bot_profile_total_ms_per_tick_p90": {"count": 9, "mean": 3.0},
                "bot_profile_total_ms_per_tick_p99": {"count": 9, "mean": 4.5},
            },
            "by_selector": {
                "boost:climb:high:full": {
                    "runs": 10,
                    "successes": 9,
                    "crashed": 1,
                    "success_rate": 0.9,
                    "efficiency_success": {
                        "fuel_consumed": {"count": 9, "mean": 21.0, "stddev": 2.5},
                        "time": {"count": 9, "mean": 14.0, "stddev": 1.25},
                        "landing_offset": {"count": 9, "mean": 6.25, "stddev": 2.0},
                        "trace_ref_gap_mean": {
                            "count": 9,
                            "mean": 5.0,
                            "stddev": 1.0,
                        },
                        "trace_ref_gap_area": {
                            "count": 9,
                            "mean": 18.75,
                            "stddev": 4.5,
                        },
                        "trace_ref_gap_max": {
                            "count": 9,
                            "mean": 7.5,
                            "max": 13.5,
                            "stddev": 2.25,
                        },
                        "bot_profile_total_ms_per_tick": {"count": 9, "mean": 1.75},
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
                "landing_offset": 14.25,
                "trace_ref_gap_mean": 6.0,
                "trace_ref_gap_area": 22.5,
                "trace_ref_gap_max": 16.0,
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
        "baseline_json_path": str(baseline_json.resolve()),
        "candidate_json_path": str(candidate_json.resolve()),
        "baseline_commit": "base",
        "candidate_commit": "head",
        "notable_regression": True,
        "global": {
            "summary_available": True,
            "summary_baseline": {
                "runs": 10.0,
                "successes": 10.0,
                "success_rate": 1.0,
                "crashed": 0.0,
                "fuel_mean_all": 18.5,
                "fuel_mean_success": 18.5,
                "time_mean_all": 12.8,
                "time_mean_success": 12.8,
                "ref_gap_mean_mean_success": 3.8,
                "ref_gap_peak_max_success": 9.8,
            },
            "summary_candidate": {
                "runs": 10.0,
                "successes": 9.0,
                "success_rate": 0.9,
                "crashed": 1.0,
                "fuel_mean_all": 13.5,
                "fuel_mean_success": 21.0,
                "time_mean_all": 9.25,
                "time_mean_success": 14.0,
                "ref_gap_mean_mean_success": 5.0,
                "ref_gap_peak_max_success": 13.5,
            },
            "summary_delta": {
                "success_rate": -0.1,
                "crashed": 1.0,
                "fuel_mean_all": -5.0,
                "fuel_mean_success": 2.5,
                "time_mean_all": -3.55,
                "time_mean_success": 1.2,
            },
            "compare_basis": {
                "mode": "aligned_runs",
                "shared_runs": 10,
                "candidate_only_runs": 0,
                "baseline_only_runs": 0,
            },
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
                    "delta_ref_gap_mean": 1.2,
                    "delta_ref_gap_area": 7.8,
                    "delta_ref_gap_peak_max": 3.5,
                    "fuel_basis": "success",
                    "ref_gap_basis": "success_only",
                }
            ],
            "compute": {},
        },
    }
    intent_payload = {
        "schema": "pylander.benchmark.intent.v1",
        "goal_summary": "Check boost climb tuning against the last behavior change",
        "request_source": "mixed",
        "conversation_context": [
            "User asked for a full regression pass after boost tuning."
        ],
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
        "follow_ups": ["uv run python main.py plot boost:climb:high:full:0 --bot pdg"],
    }

    candidate_json.write_text(json.dumps(candidate_payload), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")
    baseline_payload = {
        **candidate_payload,
        "benchmark_wall_clock_s": 10.0,
        "trace_root_path": str(baseline_root),
        "trace_root_rel": "benchmarks/base/full_pack.tracepack",
        "summary": {
            **candidate_payload["summary"],
            "successes": 10,
            "crashed": 0,
            "success_rate": 1.0,
            "by_selector": {
                "boost:climb:high:full": {
                    "runs": 10,
                    "successes": 10,
                    "crashed": 0,
                    "success_rate": 1.0,
                    "efficiency_success": {
                        "fuel_consumed": {"count": 10, "mean": 18.5, "stddev": 1.2},
                        "time": {"count": 10, "mean": 12.8, "stddev": 0.75},
                        "landing_offset": {"count": 10, "mean": 4.25, "stddev": 1.25},
                        "trace_ref_gap_mean": {"count": 10, "mean": 3.8, "stddev": 0.6},
                        "trace_ref_gap_area": {
                            "count": 10,
                            "mean": 11.2,
                            "stddev": 2.4,
                        },
                        "trace_ref_gap_max": {
                            "count": 10,
                            "mean": 5.4,
                            "max": 9.8,
                            "stddev": 1.2,
                        },
                    },
                }
            },
        },
        "records": [
            {
                **candidate_payload["records"][0],
                "success": True,
                "state": "landed",
                "failure_mode": "none",
                "fuel_consumed": 9.0,
                "time": 11.5,
                "landing_offset": 4.0,
                "trace_ref_gap_mean": 3.5,
                "trace_ref_gap_area": 10.5,
                "trace_ref_gap_max": 8.5,
                "trace_path": str(baseline_trace_path),
                "trace_rel_path": "benchmarks/base/full_pack.tracepack/traces/boost_climb_high_full_0.trace.json",
                "trace_preview_path": str(baseline_preview_path),
                "trace_preview_rel_path": "benchmarks/base/full_pack.tracepack/previews/boost_climb_high_full_0.png",
            }
        ],
    }
    baseline_json.write_text(json.dumps(baseline_payload), encoding="utf-8")
    baseline_meta.write_text("{}", encoding="utf-8")
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
        baseline_json_path=baseline_json,
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
    baseline_detail_html = (
        outputs_root
        / "viewer"
        / "bundles"
        / "bundle_x"
        / "runs"
        / "baseline"
        / "boost_climb_high_full_0.html"
    ).read_text(encoding="utf-8")

    assert "Overview" in html_payload
    assert "<h2>Comparison</h2>" not in html_payload
    assert "<title>Full Pack Benchmark Compare</title>" in html_payload
    assert "<h1>Full Pack Benchmark Compare</h1>" in html_payload
    assert "fuel success" in html_payload
    assert "time success" in html_payload
    assert "gap mean" in html_payload
    assert "bot p99" in html_payload
    assert "Tracepack Mode" in html_payload
    assert "Expand Scenarios" in html_payload
    assert "Collapse Scenarios" in html_payload
    assert "Expand All" in html_payload
    assert "Collapse All" in html_payload
    assert "Context" in html_payload
    assert "Outcome" in html_payload
    assert "Analysis" in html_payload
    assert "Compare Basis" in html_payload
    assert "aligned_runs (shared 10, current-only 0, baseline-only 0)" in html_payload
    assert "<h2>Compare</h2>" not in html_payload
    assert "<h2>Baseline</h2>" not in html_payload
    assert "Stability" not in html_payload
    assert "candidate json" not in html_payload
    assert "intent json" not in html_payload
    assert "analysis json" not in html_payload
    assert "baseline json" not in html_payload
    assert "Compared Refs" not in html_payload
    assert "Compared Tracepacks" not in html_payload
    assert "<th>Tracepack</th>" not in html_payload
    assert "<th>Efficiency</th>" in html_payload
    assert "<th>Tracking</th>" in html_payload
    assert "<th>Compute</th>" in html_payload
    assert "<th>Wall Clock</th>" in html_payload
    assert "<code>head</code>" in html_payload
    assert "<code>base</code>" in html_payload
    assert "9/10 (90.00%)" in html_payload
    assert "10/10 (100.00%)" in html_payload
    assert "12.500" in html_payload
    assert "10.000" in html_payload
    assert "2.500" in html_payload
    assert '<span class="row-tag candidate">current</span>' in html_payload
    assert '<span class="row-tag baseline">baseline</span>' in html_payload
    assert '<span class="row-tag diff">diff</span>' in html_payload
    assert 'class="summary-row"' in html_payload
    assert 'class="baseline-summary-row baseline-row"' in html_payload
    assert 'class="diff-summary-row"' in html_payload
    assert "Check boost climb tuning against the last behavior change" in html_payload
    assert "Boost climb success rate regressed with one new crash." in html_payload
    assert "<th>Details</th>" in html_payload
    assert "Delta Ref Gap" not in html_payload
    assert "Delta Ref Peak" not in html_payload
    assert "boost:climb:high:full" in html_payload
    assert "Hide Baseline" in html_payload
    assert 'data-action="toggle-baseline"' in html_payload
    assert html_payload.index("Hide Baseline") < html_payload.index("Expand Scenarios")
    assert html_payload.index("Expand Scenarios") < html_payload.index("Expand All")
    assert html_payload.index("Collapse Scenarios") < html_payload.index("Collapse All")
    assert ">cur<" in html_payload
    assert ">base<" in html_payload
    assert 'class="baseline-scenario-row baseline-row"' in html_payload
    assert 'class="seed-row baseline-seed-row baseline-row"' in html_payload
    assert ">base</span>seed 0" in html_payload
    assert "21.00 ± 11.9%" in html_payload
    assert "18.50 ± 6.5%" in html_payload
    assert "14.00 ± 8.9%" in html_payload
    assert "12.80 ± 5.9%" in html_payload
    assert "offset μ/σ" in html_payload
    assert "ref gap μ/±%" in html_payload
    assert "5.000 ± 20.0%" in html_payload
    assert "3.800 ± 15.8%" in html_payload
    assert "ref peak max" in html_payload
    assert "13.500" in html_payload
    assert "9.800" in html_payload
    assert html_payload.index("<h2>Boost</h2>") < html_payload.index(
        "<h2>Failures</h2>"
    )
    assert ">latest</a>" in html_payload
    assert 'href="../../latest/index.html"' in html_payload
    assert (
        'document.querySelectorAll(".scenario-table").forEach((table) => {'
        in html_payload
    )
    assert "expandScenarios(table);" in html_payload
    assert (
        "../../../benchmarks/head/full_pack.tracepack/previews/boost_climb_high_full_0.png"
        in html_payload
    )
    assert (
        "../../../benchmarks/base/full_pack.tracepack/previews/boost_climb_high_full_0.png"
        in html_payload
    )
    assert 'table.classList.toggle("baseline-hidden");' in html_payload
    assert (
        'button.textContent = table.classList.contains("baseline-hidden")'
        in html_payload
    )
    assert "compare-stack" not in html_payload
    assert "plot pack" not in html_payload.lower()
    assert "Tracepacks" not in latest_payload
    assert "Redirecting to the latest report" in latest_payload
    assert 'window.location.replace("../bundles/bundle_x/index.html")' in latest_payload
    assert 'content="0; url=../bundles/bundle_x/index.html"' in latest_payload
    assert "../bundles/bundle_x/runs/boost_climb_high_full_0.html" not in latest_payload
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
    assert (
        bundle_json_payload["compare"]["baseline_json_path"]
        == "benchmarks/base/full_pack.tracepack.json"
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
    assert (
        'name: String(reference.label || plotPayload.reference_label || "reference")'
        in detail_html
    )
    assert "ballistic ref (vx adjusted)" in detail_html
    assert "bundle report" not in detail_html
    assert "latest page" not in detail_html
    assert ">back<" in detail_html
    assert 'href="../index.html"' in detail_html
    assert "trace json" in detail_html
    assert "plot manifest" not in detail_html
    assert "https://cdn.plot.ly/plotly-basic-2.35.2.min.js" in detail_html
    assert "baseline json" in baseline_detail_html
    assert (
        "../../../../../benchmarks/base/full_pack.tracepack.json"
        in baseline_detail_html
    )
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
        baseline_json_path=baseline_json,
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
    rendered_payload = json.loads(rendered.bundle_json_path.read_text(encoding="utf-8"))
    assert rendered.bundle_page_path.exists()
    assert (
        rendered_payload["compare"]["json_path"]
        == "benchmarks/head/full_pack.compare.json"
    )
    assert (
        rendered_payload["compare"]["baseline_json_path"]
        == "benchmarks/base/full_pack.tracepack.json"
    )
    assert rendered_payload["benchmark"]["candidate"]["cached"] == "True"
    assert rendered_payload["intent"]["goal_summary"].startswith("Check boost climb")
    assert rendered_payload["analysis"]["verdict"] == "regression"

    single_rendered = trace_bundle.render_bundle(
        candidate_json_path=candidate_json,
        candidate_meta_path=candidate_meta,
        compare_path=None,
        baseline_json_path=None,
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
        benchmark_exit_code=0,
        benchmark_wall_clock_s=1.0,
        outputs_root=outputs_root,
        bundle_id="bundle_single_x",
        candidate_cached="True",
    )
    single_html = single_rendered.bundle_page_path.read_text(encoding="utf-8")
    assert 'data-action="toggle-baseline"' not in single_html
    assert 'class="baseline-scenario-row baseline-row"' not in single_html
    assert ">base<" not in single_html


def test_render_bundle_rejects_mismatched_explicit_baseline_json(
    tmp_path: Path,
) -> None:
    outputs_root = tmp_path / "outputs"
    outputs_root.mkdir()
    candidate_json = outputs_root / "benchmarks" / "head" / "pack.tracepack.json"
    baseline_json = outputs_root / "benchmarks" / "base" / "pack.tracepack.json"
    other_baseline_json = outputs_root / "benchmarks" / "other" / "pack.tracepack.json"
    compare_json = outputs_root / "benchmarks" / "head" / "pack.compare.json"
    for path in (candidate_json, baseline_json, other_baseline_json, compare_json):
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": "pylander.tracepack.v1", "summary": {}, "records": []}
    candidate_json.write_text(json.dumps(payload), encoding="utf-8")
    baseline_json.write_text(json.dumps(payload), encoding="utf-8")
    other_baseline_json.write_text(json.dumps(payload), encoding="utf-8")
    compare_json.write_text(
        json.dumps(
            {
                "baseline_commit": "base",
                "candidate_commit": "head",
                "baseline_json_path": str(baseline_json.resolve()),
                "candidate_json_path": str(candidate_json.resolve()),
                "global": {"compare_basis": {"mode": "aligned_runs", "shared_runs": 0}},
            }
        ),
        encoding="utf-8",
    )

    try:
        trace_bundle.render_bundle(
            candidate_json_path=candidate_json,
            candidate_meta_path=None,
            compare_path=compare_json,
            baseline_json_path=other_baseline_json,
            intent_path=None,
            analysis_path=None,
            benchmark_cmd=[],
            benchmark_exit_code=0,
            benchmark_wall_clock_s=0.0,
            outputs_root=outputs_root,
            bundle_id="bundle_bad",
        )
    except SystemExit as exc:
        assert "does not match compare JSON baseline" in str(exc)
    else:
        raise AssertionError("expected mismatched baseline json to raise SystemExit")


def test_render_bundle_uses_candidate_wall_clock_when_report_arg_missing(
    tmp_path: Path,
) -> None:
    outputs_root = tmp_path / "outputs"
    outputs_root.mkdir()
    candidate_json = outputs_root / "benchmarks" / "head" / "pack.tracepack.json"
    candidate_meta = outputs_root / "benchmarks" / "head" / "pack.meta.json"
    candidate_json.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": "pylander.tracepack.v1",
        "benchmark_wall_clock_s": 12.5,
        "summary": {
            "runs": 1,
            "successes": 1,
            "crashed": 0,
            "success_rate": 1.0,
        },
        "records": [],
    }
    candidate_json.write_text(json.dumps(payload), encoding="utf-8")
    candidate_meta.write_text("{}", encoding="utf-8")

    rendered = trace_bundle.render_bundle(
        candidate_json_path=candidate_json,
        candidate_meta_path=candidate_meta,
        compare_path=None,
        baseline_json_path=None,
        intent_path=None,
        analysis_path=None,
        benchmark_cmd=[],
        benchmark_exit_code=0,
        benchmark_wall_clock_s=None,
        outputs_root=outputs_root,
        bundle_id="bundle_candidate_clock",
        candidate_cached="True",
    )

    bundle_json_payload = json.loads(
        rendered.bundle_json_path.read_text(encoding="utf-8")
    )
    html_payload = rendered.bundle_page_path.read_text(encoding="utf-8")

    assert bundle_json_payload["timing"]["benchmark_wall_clock_s"] == 12.5
    assert (
        bundle_json_payload["benchmark"]["candidate"]["benchmark_wall_clock_s"] == 12.5
    )
    assert "<th>Wall Clock</th>" in html_payload
    assert "12.500" in html_payload
