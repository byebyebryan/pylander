from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_csv(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values:
        for token in str(item).split(","):
            t = token.strip()
            if t:
                out.append(t)
    return out


def _selector_from_record(record: dict[str, Any]) -> str:
    level = str(record.get("level") or "").strip() or "unknown"
    scenario = str(record.get("scenario") or "").strip()
    eval_goal = str(record.get("eval_goal") or record.get("bot_eval_goal") or "landing").strip().lower()
    if not eval_goal:
        eval_goal = "landing"
    seed = record.get("seed")
    seed_token: str | None = None
    if seed is not None:
        try:
            seed_token = str(int(seed))
        except (TypeError, ValueError):
            seed_token = str(seed)

    has_scenario = bool(scenario and scenario != level)
    if has_scenario:
        base = f"{level}:{scenario}"
    else:
        base = level
    if eval_goal == "landing":
        if seed_token is None:
            return base
        if has_scenario:
            return f"{base}:{seed_token}"
        return f"{base}::{seed_token}"

    goal_base = (
        f"{level}:{scenario}:{eval_goal}"
        if has_scenario
        else f"{level}::{eval_goal}"
    )
    if seed_token is None:
        return goal_base
    return f"{goal_base}:{seed_token}"


def _selector_from_triplet(
    level: str,
    scenario: str,
    seed: int | str | None,
    *,
    eval_goal: str = "landing",
) -> str:
    level_t = str(level or "").strip() or "unknown"
    scenario_t = str(scenario or "").strip()
    seed_t = "0" if seed is None else str(seed)
    goal_t = str(eval_goal or "landing").strip().lower() or "landing"
    if goal_t == "landing":
        if scenario_t and scenario_t != level_t:
            return f"{level_t}:{scenario_t}:{seed_t}"
        return f"{level_t}::{seed_t}"
    if scenario_t and scenario_t != level_t:
        return f"{level_t}:{scenario_t}:{goal_t}:{seed_t}"
    return f"{level_t}::{goal_t}:{seed_t}"


def _abs_float(value: Any) -> float:
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def _build_cases_from_records(records: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    for rec in records:
        if str(rec.get("state") or "") == "crashed":
            cases.append(
                {
                    "selector": _selector_from_record(rec),
                    "severity": "critical",
                    "reason": "crash",
                    "evidence": {
                        "state": rec.get("state"),
                        "failure_mode": rec.get("failure_mode"),
                    },
                }
            )

    ranked = sorted(
        records,
        key=lambda r: (
            _abs_float(r.get("zem_setup_gate_projected_dx")),
            _abs_float(r.get("zem_terminal_gate_projected_dx")),
            _abs_float(r.get("fuel_consumed")),
        ),
        reverse=True,
    )
    for rec in ranked:
        setup_dx = _abs_float(rec.get("zem_setup_gate_projected_dx"))
        terminal_dx = _abs_float(rec.get("zem_terminal_gate_projected_dx"))
        fuel = _abs_float(rec.get("fuel_consumed"))
        if setup_dx <= 0.0 and terminal_dx <= 0.0 and fuel <= 0.0:
            continue
        reason = "high_setup_dx" if setup_dx >= terminal_dx else "high_terminal_dx"
        if setup_dx < 1.0 and terminal_dx < 1.0:
            reason = "high_fuel"
        severity = "high" if setup_dx >= 100.0 or terminal_dx >= 50.0 else "medium"
        cases.append(
            {
                "selector": _selector_from_record(rec),
                "severity": severity,
                "reason": reason,
                "evidence": {
                    "zem_setup_gate_projected_dx": rec.get("zem_setup_gate_projected_dx"),
                    "zem_terminal_gate_projected_dx": rec.get("zem_terminal_gate_projected_dx"),
                    "fuel_consumed": rec.get("fuel_consumed"),
                },
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        selector = str(case.get("selector") or "").strip()
        if not selector or selector in seen:
            continue
        seen.add(selector)
        deduped.append(case)
        if len(deduped) >= max(1, int(top_n)):
            break
    return deduped


def _build_cases_from_compare(compare: dict[str, Any], *, top_n: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    global_block = dict(compare.get("global") or {})
    crash_block = dict(global_block.get("crash") or {})
    for item in crash_block.get("new_crashes") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "selector": _selector_from_triplet(
                    str(item.get("level") or "unknown"),
                    str(item.get("scenario") or ""),
                    item.get("seed"),
                    eval_goal=str(item.get("eval_goal") or "landing"),
                ),
                "severity": "critical",
                "reason": "new_global_crash",
                "evidence": {
                    "candidate_failure_mode": item.get("candidate_failure_mode"),
                    "baseline_state": item.get("baseline_state"),
                    "candidate_state": item.get("candidate_state"),
                },
            }
        )

    worst = global_block.get("worst_scenarios") or []
    for row in worst:
        if not isinstance(row, dict):
            continue
        scenario = str(row.get("scenario") or "").strip()
        if not scenario:
            continue
        parts = scenario.split(":", 1)
        if len(parts) != 2:
            continue
        level_name, scenario_name = parts
        out.append(
            {
                "selector": _selector_from_triplet(level_name, scenario_name, 0),
                "severity": "high",
                "reason": "worst_scenario_regression",
                "evidence": {
                    "delta_success_rate": row.get("delta_success_rate"),
                    "delta_fuel_mean": row.get("delta_fuel_mean"),
                },
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for case in out:
        selector = str(case.get("selector") or "").strip()
        if not selector or selector in seen:
            continue
        seen.add(selector)
        deduped.append(case)
        if len(deduped) >= max(1, int(top_n)):
            break
    return deduped


def _extract_paths(output: str) -> dict[str, Any]:
    png_pattern = re.compile(r"(?:^|\s)(outputs/[^\s]+\.png|/[^\s]+\.png)")
    manifest_pattern = re.compile(r"Plot manifest:\s+(.+)$", re.MULTILINE)
    plots: list[str] = []
    for match in png_pattern.finditer(output):
        candidate = match.group(1).strip()
        if candidate not in plots:
            plots.append(candidate)
    manifest_match = manifest_pattern.search(output)
    manifest_path = manifest_match.group(1).strip() if manifest_match else None
    return {
        "plot_paths": plots,
        "plot_manifest_path": manifest_path,
    }


def _run_plot_command(
    selector: str,
    *,
    bot: str,
    plot_mode: str,
    plot_output: str,
    plot_max_side_px: int,
) -> dict[str, Any]:
    cmd = [
        "uv",
        "run",
        "python",
        "main.py",
        "plot",
        selector,
        "--bot",
        bot,
        "--plot",
        plot_mode,
        "--plot-output",
        plot_output,
        "--plot-max-side-px",
        str(max(256, int(plot_max_side_px))),
    ]
    proc = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = str(proc.stdout or "")
    extracted = _extract_paths(output)
    return {
        "command": cmd,
        "exit_code": int(proc.returncode),
        "output": output,
        **extracted,
    }


def _default_pack_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return (_REPO_ROOT / "outputs" / "plots" / f"pack_{ts}.json").resolve()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build and optionally execute Pylander plot packs")
    ap.add_argument("--mode", choices=("health", "compare", "focus", "triage"), required=True)
    ap.add_argument("--benchmark-json", type=str, default=None)
    ap.add_argument("--compare-json", type=str, default=None)
    ap.add_argument("--selectors", nargs="*", default=[])
    ap.add_argument("--bot", default="zem_zev")
    ap.add_argument("--top-n", type=int, default=8)
    ap.add_argument("--plot-mode", default="all", choices=("speed", "thrust", "all"))
    ap.add_argument("--plot-output", default="both", choices=("combined", "split", "both"))
    ap.add_argument("--plot-max-side-px", type=int, default=1800)
    ap.add_argument("--execute", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--output-manifest", type=str, default=None)
    args = ap.parse_args()

    benchmark_payload = _load_json(Path(args.benchmark_json)) if args.benchmark_json else None
    compare_payload = _load_json(Path(args.compare_json)) if args.compare_json else None

    top_n = max(1, int(args.top_n))
    cases: list[dict[str, Any]] = []

    if args.mode == "focus":
        selectors = _split_csv(list(args.selectors or []))
        if not selectors:
            raise SystemExit("focus mode requires --selectors")
        for selector in selectors[:top_n]:
            cases.append(
                {
                    "selector": selector,
                    "severity": "manual",
                    "reason": "focus_selector",
                    "evidence": {},
                }
            )
    elif args.mode in {"compare", "triage"}:
        if compare_payload is not None:
            cases.extend(_build_cases_from_compare(compare_payload, top_n=top_n))
        if benchmark_payload is not None and len(cases) < top_n:
            records = [dict(r) for r in (benchmark_payload.get("records") or []) if isinstance(r, dict)]
            for case in _build_cases_from_records(records, top_n=top_n):
                if any(str(c.get("selector")) == str(case.get("selector")) for c in cases):
                    continue
                cases.append(case)
                if len(cases) >= top_n:
                    break
    else:
        if benchmark_payload is None:
            raise SystemExit("health mode requires --benchmark-json")
        records = [dict(r) for r in (benchmark_payload.get("records") or []) if isinstance(r, dict)]
        cases = _build_cases_from_records(records, top_n=top_n)

    if not cases:
        raise SystemExit("No plot cases resolved")

    case_runs: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, start=1):
        selector = str(case.get("selector") or "").strip()
        if not selector:
            continue
        if not args.execute:
            case_runs.append(
                {
                    **case,
                    "index": idx,
                    "command": [
                        "uv",
                        "run",
                        "python",
                        "main.py",
                        "plot",
                        selector,
                        "--bot",
                        args.bot,
                        "--plot",
                        args.plot_mode,
                        "--plot-output",
                        args.plot_output,
                        "--plot-max-side-px",
                        str(max(256, int(args.plot_max_side_px))),
                    ],
                    "exit_code": None,
                    "plot_paths": [],
                    "plot_manifest_path": None,
                }
            )
            continue

        run = _run_plot_command(
            selector,
            bot=args.bot,
            plot_mode=args.plot_mode,
            plot_output=args.plot_output,
            plot_max_side_px=max(256, int(args.plot_max_side_px)),
        )
        case_runs.append(
            {
                **case,
                "index": idx,
                "command": run["command"],
                "exit_code": run["exit_code"],
                "plot_paths": run["plot_paths"],
                "plot_manifest_path": run.get("plot_manifest_path"),
            }
        )

    manifest_path = Path(args.output_manifest).resolve() if args.output_manifest else _default_pack_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": args.mode,
        "bot": args.bot,
        "plot_mode": args.plot_mode,
        "plot_output": args.plot_output,
        "plot_max_side_px": max(256, int(args.plot_max_side_px)),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_json": args.benchmark_json,
        "compare_json": args.compare_json,
        "cases": case_runs,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"# plot_pack\nmanifest={manifest_path}\ncases={len(case_runs)}")


if __name__ == "__main__":
    main()
