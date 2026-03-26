from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_ROOT = (_REPO_ROOT / ".agents").resolve()
for candidate in (_AGENTS_ROOT, _REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from skills.lib.contracts import validate_contract_data  # noqa: E402
from skills.lib.orchestration import (  # noqa: E402
    load_json,
    parse_compare_report_path,
    run_command,
    to_float,
    utc_now_iso,
    write_json,
)


def _verdict(compare: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    global_block = dict(compare.get("global") or {})
    crash = dict(global_block.get("crash") or {})
    summary_delta = dict(global_block.get("summary_delta") or {})
    compute = dict(global_block.get("compute") or {})

    new_global_crashes = len(list(crash.get("new_crashes") or []))
    delta_success_rate = to_float(summary_delta.get("success_rate"), 0.0)
    notable_global_regression = bool(global_block.get("notable_regression", False))
    notable_global_compute = bool(compute.get("notable_regression", False))

    if new_global_crashes > 0:
        gate = "revert"
    elif delta_success_rate < -0.02:
        gate = "revert"
    elif notable_global_regression or notable_global_compute:
        gate = "investigate"
    else:
        gate = "keep"

    follow_ups: list[str] = []
    for crash_item in list(crash.get("new_crashes") or [])[:5]:
        if not isinstance(crash_item, dict):
            continue
        repro = dict(crash_item.get("repro") or {})
        for key in ("plot", "sim_trace", "sim_profile"):
            cmd = str(repro.get(key) or "").strip()
            if cmd and cmd not in follow_ups:
                follow_ups.append(cmd)

    for row in list(global_block.get("worst_scenarios") or [])[:3]:
        if not isinstance(row, dict):
            continue
        scenario = str(row.get("scenario") or "").strip()
        if scenario:
            follow_ups.append(
                "uv run python main.py plot "
                f"{scenario}:0 --bot pdg --plot all --plot-output both"
            )

    evidence = {
        "new_global_crashes": new_global_crashes,
        "delta_success_rate": delta_success_rate,
        "notable_global_regression": notable_global_regression,
        "notable_global_compute": notable_global_compute,
    }
    return gate, evidence, follow_ups


def _run_compare(payload: dict[str, Any]) -> str:
    mode = str(payload.get("mode") or "quick").strip().lower()
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be quick or full")

    bot = str(payload.get("bot") or "pdg")
    baseline_ref = str(payload.get("baseline_ref") or "main").strip() or "main"
    bot_config_path = str(payload.get("bot_config_path") or "").strip()

    cmd = [
        "uv",
        "run",
        "python",
        ".agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
        "--mode",
        mode,
        "--baseline-ref",
        baseline_ref,
        "--bot",
        bot,
    ]
    if bot_config_path:
        cmd += ["--bot-config", bot_config_path]

    code, output = run_command(cmd, cwd=_REPO_ROOT)
    if code != 0:
        raise RuntimeError(
            f"regression compare command failed with exit code {code}\n{output}"
        )
    compare_path = parse_compare_report_path(output)
    if not compare_path:
        raise RuntimeError("Unable to parse compare_report path from benchmark output")
    return compare_path


def gate_regression(payload: dict[str, Any], *, execute: bool) -> dict[str, Any]:
    mode = str(payload.get("mode") or "quick").strip().lower()
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be quick or full")

    baseline_ref = str(payload.get("baseline_ref") or "main").strip() or "main"

    compare_report_path = str(payload.get("compare_report_path") or "").strip()
    if not compare_report_path:
        if not execute:
            raise ValueError("compare_report_path is required when --no-execute is set")
        compare_report_path = _run_compare(payload)

    compare = load_json(compare_report_path)
    gate, evidence, follow_ups = _verdict(compare)

    out = {
        "contract": "regression_gate_report.v1",
        "mode": mode,
        "baseline_ref": baseline_ref,
        "compare_report_path": str(Path(compare_report_path).resolve()),
        "gate_verdict": gate,
        "evidence": evidence,
        "follow_ups": follow_ups,
        "created_at_utc": utc_now_iso(),
    }
    validate_contract_data(out, "regression_gate_report.v1")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate Pylander broad regression state")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument(
        "--execute",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Execute benchmark compare when compare_report_path is missing",
    )
    args = ap.parse_args()

    payload = load_json(args.input)
    report = gate_regression(payload, execute=bool(args.execute))
    out_path = write_json(args.output, report)
    print(f"# regression_gate\njson={out_path}")


if __name__ == "__main__":
    main()
