from __future__ import annotations

import json
from pathlib import Path

import bot_framework.benchmark_promote as benchmark_promote


def _write_candidate_cache(tmp_path: Path) -> tuple[Path, Path]:
    outputs_root = (tmp_path / "outputs").resolve()
    results_root = outputs_root / "benchmarks"
    commit = "4869be4-dirty-97df1b28ee"
    stem = "quick_boost_n1_deadbeef00"
    out_dir = results_root / commit
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_json = (out_dir / f"{stem}.tracepack.json").resolve()
    candidate_meta = (out_dir / f"{stem}.meta.json").resolve()
    trace_root = candidate_json.with_suffix("")
    trace_path = (trace_root / "traces" / "boost_flat_mid_half_0.trace.json").resolve()
    preview_path = (trace_root / "previews" / "boost_flat_mid_half_0.png").resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("{}", encoding="utf-8")
    preview_path.write_bytes(b"png")

    candidate_payload = {
        "schema": "pylander.tracepack.v1",
        "schema_version": 3,
        "trace_detail": "report",
        "trace_root_path": str(trace_root),
        "trace_root_rel": trace_root.relative_to(outputs_root).as_posix(),
        "run_index": [
            {
                "selector": "boost:flat:mid:half:0",
                "run_key": "boost:flat:mid:half:0",
                "run_instance_id": 1,
                "trace_path": str(trace_path),
                "trace_rel_path": trace_path.relative_to(outputs_root).as_posix(),
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": preview_path.relative_to(
                    outputs_root
                ).as_posix(),
            }
        ],
        "records": [
            {
                "level": "boost",
                "scenario": "flat:mid:half",
                "seed": 0,
                "trace_path": str(trace_path),
                "trace_rel_path": trace_path.relative_to(outputs_root).as_posix(),
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": preview_path.relative_to(
                    outputs_root
                ).as_posix(),
            }
        ],
    }
    candidate_json.write_text(
        json.dumps(candidate_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    candidate_meta.write_text(
        json.dumps(
            {
                "commit": commit,
                "json_path": str(candidate_json),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    intent_path = candidate_json.with_name(f"{candidate_json.stem}.intent.json")
    analysis_path = candidate_json.with_name(f"{candidate_json.stem}.analysis.json")
    inspect_path = candidate_json.with_name(f"{candidate_json.stem}.inspect.json")
    compare_path = candidate_json.with_name(
        f"{candidate_json.stem}.compare_vs_5225400_deadbeef.json"
    )
    intent_path.write_text(
        json.dumps(
            {
                "outputs": {
                    "candidate_commit": commit,
                    "candidate_json": str(candidate_json),
                    "intent_json": str(intent_path),
                    "results_root": str(results_root),
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    analysis_path.write_text(
        json.dumps(
            {
                "candidate_json": str(candidate_json),
                "verdict": "no_change",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    inspect_path.write_text(
        json.dumps(
            {"schema": "pylander.benchmark.inspect.v1"}, indent=2, sort_keys=True
        ),
        encoding="utf-8",
    )
    compare_path.write_text(
        json.dumps(
            {
                "candidate_commit": commit,
                "baseline_commit": "5225400",
                "notable_regression": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return outputs_root, candidate_json


def test_promote_cache_rewrites_tracepack_and_sidecars(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outputs_root, candidate_json = _write_candidate_cache(tmp_path)
    monkeypatch.setattr(benchmark_promote, "git_rev_parse", lambda ref: "ce8fed5")

    result = benchmark_promote.promote_cache(
        candidate_json_path=candidate_json,
        target_ref="HEAD",
    )

    target_json = result["candidate_json"]
    target_meta = result["candidate_meta"]
    target_trace_root = target_json.with_suffix("")
    promoted_payload = json.loads(target_json.read_text(encoding="utf-8"))
    promoted_meta = json.loads(target_meta.read_text(encoding="utf-8"))
    promoted_intent = json.loads(
        target_json.with_name(f"{target_json.stem}.intent.json").read_text(
            encoding="utf-8"
        )
    )
    promoted_analysis = json.loads(
        target_json.with_name(f"{target_json.stem}.analysis.json").read_text(
            encoding="utf-8"
        )
    )
    promoted_compare = json.loads(result["compare_json"].read_text(encoding="utf-8"))

    assert target_json.parent.name == "ce8fed5"
    assert promoted_payload["trace_root_path"] == str(target_trace_root)
    assert promoted_payload["trace_root_rel"].startswith("benchmarks/ce8fed5/")
    assert promoted_payload["run_index"][0]["trace_rel_path"].startswith(
        "benchmarks/ce8fed5/"
    )
    assert promoted_payload["records"][0]["trace_path"].startswith(
        str(target_trace_root)
    )
    assert promoted_meta["commit"] == "ce8fed5"
    assert promoted_intent["outputs"]["candidate_commit"] == "ce8fed5"
    assert promoted_intent["outputs"]["candidate_json"] == str(target_json)
    assert promoted_analysis["candidate_json"] == str(target_json)
    assert promoted_compare["candidate_commit"] == "ce8fed5"
    assert promoted_payload["promotion"]["promoted_to_commit"] == "ce8fed5"
    assert (target_trace_root / "traces" / "boost_flat_mid_half_0.trace.json").exists()
    assert (target_trace_root / "previews" / "boost_flat_mid_half_0.png").exists()
    assert (
        target_json.relative_to(outputs_root)
        .as_posix()
        .startswith("benchmarks/ce8fed5/")
    )
