from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.eval import aggregate_eval_records  # noqa: E402

from build_selector_pack import (  # noqa: E402
    ResolvedSelectorPack,
    build_bench_command,
    build_selectors,
)

_COMPUTE_FIELDS: tuple[str, ...] = (
    "bot_profile_total_ms_per_tick",
    "bot_profile_passive_ms_per_tick",
    "bot_profile_active_ms_per_tick",
    "bot_profile_query_ms_per_tick",
    "bot_profile_update_ms_per_tick",
    "bot_profile_total_ms_per_tick_p90",
    "bot_profile_total_ms_per_tick_p99",
    "bot_profile_query_ms_per_tick_p90",
    "bot_profile_query_ms_per_tick_p99",
    "bot_profile_update_ms_per_tick_p90",
    "bot_profile_update_ms_per_tick_p99",
)
_COMPUTE_AVG_TOTAL_ABS_MIN = 0.10
_COMPUTE_AVG_TOTAL_REL_MIN = 0.10
_COMPUTE_AVG_COMPONENT_ABS_MIN = 0.05
_COMPUTE_AVG_COMPONENT_REL_MIN = 0.20
_COMPUTE_P99_TOTAL_ABS_MIN = 0.20
_COMPUTE_P99_TOTAL_REL_MIN = 0.20
_COMPUTE_P99_COMPONENT_ABS_MIN = 0.10
_COMPUTE_P99_COMPONENT_REL_MIN = 0.25


def _sanitize_token(value: str) -> str:
    out = []
    prev_us = False
    for ch in str(value).lower().strip():
        if ch.isalnum() or ch in ("-", "."):
            out.append(ch)
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
                prev_us = True
    token = "".join(out).strip("._")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "run"


def _git_rev_parse(ref: str) -> str:
    out = subprocess.check_output(
        ["git", "rev-parse", "--short", ref],
        cwd=_REPO_ROOT,
        text=True,
    )
    return out.strip()


def _git_output(args: list[str]) -> bytes:
    return subprocess.check_output(["git", *args], cwd=_REPO_ROOT)


def _dirty_workspace_fingerprint() -> str | None:
    status = _git_output(["status", "--porcelain=v1", "--untracked-files=all"])
    if not status.strip():
        return None

    payload = bytearray()
    payload.extend(b"STATUS\n")
    payload.extend(status)
    payload.extend(b"\nDIFF_CACHED\n")
    payload.extend(_git_output(["diff", "--cached", "--no-ext-diff", "--binary", "HEAD"]))
    payload.extend(b"\nDIFF_WORKTREE\n")
    payload.extend(_git_output(["diff", "--no-ext-diff", "--binary", "HEAD"]))

    # Include untracked file content so new local files affect cache key.
    for raw_line in status.splitlines():
        line = raw_line.decode("utf-8", errors="replace")
        if not line.startswith("?? "):
            continue
        rel_path = line[3:]
        file_path = (_REPO_ROOT / rel_path).resolve()
        payload.extend(f"\nUNTRACKED:{rel_path}\n".encode("utf-8"))
        if file_path.is_file():
            try:
                payload.extend(file_path.read_bytes())
            except Exception:
                payload.extend(b"<unreadable>")

    return hashlib.sha1(bytes(payload)).hexdigest()[:10]


def _workspace_key() -> str:
    head = _git_rev_parse("HEAD")
    dirty = _dirty_workspace_fingerprint()
    if not dirty:
        return head
    return f"{head}-dirty-{dirty}"


def _selector_pack_stem(
    *,
    mode: str,
    selectors: list[str],
    bot: str,
    eval_mode: str,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
) -> str:
    level_tokens = sorted({s.split(":", 1)[0] for s in selectors if s.strip()})
    level_hint = "-".join(level_tokens[:3]) if level_tokens else "none"
    if len(level_tokens) > 3:
        level_hint += "-etc"
    digest_payload = json.dumps(
        {
            "mode": mode,
            "selectors": selectors,
            "bot": bot,
            "eval_mode": eval_mode,
            "bot_profile_enabled": bool(bot_profile_enabled),
            "bot_profile_interval_s": (
                None if bot_profile_interval_s is None else round(float(bot_profile_interval_s), 6)
            ),
            "bot_profile_log_lines": bool(bot_profile_log_lines),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(digest_payload.encode("utf-8")).hexdigest()[:10]
    stem = f"{mode}_{level_hint}_n{len(selectors)}_{digest}"
    return _sanitize_token(stem)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _extract_summary_metrics(payload: dict[str, Any]) -> dict[str, float]:
    summary = dict(payload.get("summary") or {})
    efficiency_all = dict(summary.get("efficiency_all") or {})
    efficiency_success = dict(summary.get("efficiency_success") or {})

    def _mean(eff: dict[str, Any], field: str) -> float:
        row = dict(eff.get(field) or {})
        return float(row.get("mean", 0.0) or 0.0)

    def _count(eff: dict[str, Any], field: str) -> float:
        row = dict(eff.get(field) or {})
        return float(row.get("count", 0) or 0)

    return {
        "runs": float(summary.get("runs", 0) or 0),
        "successes": float(summary.get("successes", 0) or 0),
        "success_rate": float(summary.get("success_rate", 0.0) or 0.0),
        "crashed": float(summary.get("crashed", 0) or 0),
        "fuel_mean_all": _mean(efficiency_all, "fuel_consumed"),
        "fuel_per_distance_mean_all": _mean(efficiency_all, "fuel_per_distance"),
        "fuel_mean_success": _mean(efficiency_success, "fuel_consumed"),
        "fuel_per_distance_mean_success": _mean(efficiency_success, "fuel_per_distance"),
        "fuel_success_count": _count(efficiency_success, "fuel_consumed"),
    }


def _payload_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in payload.get("records") or []:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _build_payload_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": aggregate_eval_records(records),
        "records": records,
    }


def _record_level_policy(
    record: dict[str, Any],
    *,
    level_policy: dict[str, str],
) -> str:
    level_name = str(record.get("level") or "").strip()
    token = str(level_policy.get(level_name, "normal") or "normal").strip().lower()
    if token in {"observe_only", "excluded"}:
        return token
    return "normal"


def _partition_payload_by_policy(
    payload: dict[str, Any],
    *,
    level_policy: dict[str, str],
) -> dict[str, dict[str, Any]]:
    normal_records: list[dict[str, Any]] = []
    observation_records: list[dict[str, Any]] = []
    observe_only_records: list[dict[str, Any]] = []
    excluded_records: list[dict[str, Any]] = []
    for record in _payload_records(payload):
        policy = _record_level_policy(record, level_policy=level_policy)
        if policy == "normal":
            normal_records.append(record)
            continue
        observation_records.append(record)
        if policy == "observe_only":
            observe_only_records.append(record)
        else:
            excluded_records.append(record)

    return {
        "global": _build_payload_from_records(normal_records),
        "observation": _build_payload_from_records(observation_records),
        "observe_only": _build_payload_from_records(observe_only_records),
        "excluded": _build_payload_from_records(excluded_records),
    }


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _run_diag(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "state",
        "failure_mode",
        "time",
        "fuel_consumed",
        "fuel_per_distance",
        "landing_offset",
        "distance_flown",
        "avg_speed",
        "score",
        "zem_setup_gate_projected_dx",
        "zem_terminal_gate_projected_dx",
        "setup_phase_projected_dx",
        "coast_phase_projected_dx",
    )
    out: dict[str, Any] = {}
    for key in keys:
        if key in record:
            out[key] = record.get(key)
    return out


def _selector_from_record(record: dict[str, Any]) -> str:
    level = str(record.get("level") or "unknown").strip() or "unknown"
    scenario = str(record.get("scenario") or "").strip()
    seed = record.get("seed")
    seed_token = None
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
    if seed_token is None:
        return base
    if has_scenario:
        return f"{base}:{seed_token}"
    return f"{base}::{seed_token}"


def _records_by_key(payload: dict[str, Any]) -> dict[tuple[str, str, int], dict[str, Any]]:
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    for rec_raw in payload.get("records") or []:
        if not isinstance(rec_raw, dict):
            continue
        rec = dict(rec_raw)
        level = str(rec.get("level") or "").strip()
        scenario = str(rec.get("scenario") or "").strip()
        seed = _to_int(rec.get("seed"), 0)
        if not level:
            continue
        out[(level, scenario, seed)] = rec
    return out


def _make_repro_commands(
    record: dict[str, Any],
    *,
    bot: str,
    eval_mode: str,
) -> dict[str, str]:
    selector = _selector_from_record(record)
    return {
        "plot": (
            f"uv run python main.py plot {selector} --bot {bot} --eval-mode {eval_mode} "
            "--plot all --plot-output both --plot-max-side-px 1800"
        ),
        "sim_trace": f"uv run python main.py sim {selector} --bot {bot} --eval-mode {eval_mode} --freq 1",
        "sim_profile": (
            f"PYLANDER_BOT_PROFILE=1 uv run python main.py sim {selector} "
            f"--bot {bot} --eval-mode {eval_mode} --freq 1"
        ),
    }


def _crash_deltas(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    bot: str,
    eval_mode: str,
) -> dict[str, list[dict[str, Any]]]:
    b = _records_by_key(baseline_payload)
    c = _records_by_key(candidate_payload)
    all_keys = sorted(set(b) | set(c))

    new_crashes: list[dict[str, Any]] = []
    resolved_crashes: list[dict[str, Any]] = []
    candidate_crashes: list[dict[str, Any]] = []

    for key in all_keys:
        b_rec = b.get(key, {})
        c_rec = c.get(key, {})
        b_state = str(b_rec.get("state") or "missing")
        c_state = str(c_rec.get("state") or "missing")
        if c_state == "crashed":
            entry = {
                "level": key[0],
                "scenario": key[1],
                "seed": key[2],
                "candidate_state": c_state,
                "baseline_state": b_state,
                "candidate_failure_mode": c_rec.get("failure_mode"),
                "baseline_failure_mode": b_rec.get("failure_mode"),
                "candidate_fuel_consumed": c_rec.get("fuel_consumed"),
                "candidate_time": c_rec.get("time"),
                "candidate_metrics": _run_diag(c_rec),
                "baseline_metrics": _run_diag(b_rec),
                "repro": _make_repro_commands(c_rec, bot=bot, eval_mode=eval_mode),
            }
            candidate_crashes.append(entry)
            if b_state != "crashed":
                new_crashes.append(entry)
        elif b_state == "crashed":
            resolved_crashes.append(
                {
                    "level": key[0],
                    "scenario": key[1],
                    "seed": key[2],
                    "baseline_state": b_state,
                    "candidate_state": c_state,
                    "baseline_failure_mode": b_rec.get("failure_mode"),
                }
            )

    return {
        "new_crashes": new_crashes,
        "resolved_crashes": resolved_crashes,
        "candidate_crashes": candidate_crashes,
    }


def _scenario_regressions(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, float | str]]:
    def _by_level_scenario(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for rec in _payload_records(payload):
            level = str(rec.get("level") or "unknown").strip() or "unknown"
            scenario = str(rec.get("scenario") or "default").strip() or "default"
            key = f"{level}:{scenario}"
            buckets.setdefault(key, []).append(rec)

        out: dict[str, dict[str, Any]] = {}
        for key, records in buckets.items():
            summary = aggregate_eval_records(records)
            out[key] = {
                "success_rate": float(summary.get("success_rate", 0.0) or 0.0),
                "efficiency_success": dict(summary.get("efficiency_success") or {}),
                "efficiency_all": dict(summary.get("efficiency_all") or {}),
            }
        return out

    b = _by_level_scenario(baseline)
    c = _by_level_scenario(candidate)
    names = sorted(set(b) | set(c))
    out: list[dict[str, float | str]] = []
    for name in names:
        b_row = dict(b.get(name) or {})
        c_row = dict(c.get(name) or {})
        b_sr = float(b_row.get("success_rate", 0.0) or 0.0)
        c_sr = float(c_row.get("success_rate", 0.0) or 0.0)
        b_eff_success = dict(b_row.get("efficiency_success") or {})
        c_eff_success = dict(c_row.get("efficiency_success") or {})
        b_fuel_success = float((b_eff_success.get("fuel_consumed") or {}).get("mean", 0.0) or 0.0)
        c_fuel_success = float((c_eff_success.get("fuel_consumed") or {}).get("mean", 0.0) or 0.0)
        b_fuel_success_n = int((b_eff_success.get("fuel_consumed") or {}).get("count", 0) or 0)
        c_fuel_success_n = int((c_eff_success.get("fuel_consumed") or {}).get("count", 0) or 0)
        b_fuel_all = float(
            ((b_row.get("efficiency_all") or {}).get("fuel_consumed") or {}).get("mean", 0.0) or 0.0
        )
        c_fuel_all = float(
            ((c_row.get("efficiency_all") or {}).get("fuel_consumed") or {}).get("mean", 0.0) or 0.0
        )
        use_success = b_fuel_success_n > 0 and c_fuel_success_n > 0
        b_fuel = b_fuel_success if use_success else b_fuel_all
        c_fuel = c_fuel_success if use_success else c_fuel_all
        out.append(
            {
                "scenario": name,
                "delta_success_rate": c_sr - b_sr,
                "delta_fuel_mean": c_fuel - b_fuel,
                "fuel_basis": ("success_only" if use_success else "all_runs"),
            }
        )
    out.sort(key=lambda row: (float(row["delta_success_rate"]), -float(row["delta_fuel_mean"])))
    return out


def _weighted_profile_metric(
    records: list[dict[str, Any]],
    *,
    field: str,
) -> tuple[float | None, float, int]:
    sum_weighted = 0.0
    sum_ticks = 0.0
    profiled_runs = 0
    for record in records:
        ticks = _to_float(record.get("bot_profile_ticks"), 0.0)
        value = _to_float(record.get(field), float("nan"))
        if not (ticks > 0.0):
            continue
        if value != value:
            continue
        sum_weighted += value * ticks
        sum_ticks += ticks
        profiled_runs += 1
    if sum_ticks <= 0.0:
        return None, 0.0, 0
    return (sum_weighted / sum_ticks), sum_ticks, profiled_runs


def _compute_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    records = _payload_records(payload)
    ticks_total = 0.0
    runs_profiled = 0
    for record in records:
        ticks = _to_float(record.get("bot_profile_ticks"), 0.0)
        if ticks > 0:
            ticks_total += ticks
            runs_profiled += 1

    metrics: dict[str, float | None] = {}
    for field in _COMPUTE_FIELDS:
        value, _ticks, _runs = _weighted_profile_metric(records, field=field)
        metrics[field] = value

    available = ticks_total > 0 and any(v is not None for v in metrics.values())
    return {
        "available": bool(available),
        "ticks_total": ticks_total,
        "runs_profiled": runs_profiled,
        "metrics": metrics,
    }


def _delta_with_rel(
    baseline: float | None,
    candidate: float | None,
) -> dict[str, float | None]:
    if baseline is None or candidate is None:
        return {"baseline": baseline, "candidate": candidate, "delta_abs": None, "delta_rel": None}
    delta_abs = float(candidate) - float(baseline)
    if abs(float(baseline)) <= 1e-9:
        delta_rel = float("inf") if delta_abs > 0 else 0.0
    else:
        delta_rel = delta_abs / abs(float(baseline))
    return {
        "baseline": float(baseline),
        "candidate": float(candidate),
        "delta_abs": delta_abs,
        "delta_rel": delta_rel,
    }


def _is_notable_delta(
    delta: dict[str, float | None],
    *,
    abs_min: float,
    rel_min: float,
) -> bool:
    delta_abs = delta.get("delta_abs")
    delta_rel = delta.get("delta_rel")
    if delta_abs is None or delta_rel is None:
        return False
    if float(delta_abs) <= 0.0:
        return False
    if float(delta_abs) < float(abs_min):
        return False
    if float(delta_rel) < float(rel_min):
        return False
    return True


def _compute_compare(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    b = _compute_snapshot(baseline_payload)
    c = _compute_snapshot(candidate_payload)
    deltas: dict[str, dict[str, float | None]] = {}
    for field in _COMPUTE_FIELDS:
        deltas[field] = _delta_with_rel(
            b.get("metrics", {}).get(field),
            c.get("metrics", {}).get(field),
        )

    thresholds = {
        "avg_total": {
            "abs_min_ms": _COMPUTE_AVG_TOTAL_ABS_MIN,
            "rel_min": _COMPUTE_AVG_TOTAL_REL_MIN,
        },
        "avg_component": {
            "abs_min_ms": _COMPUTE_AVG_COMPONENT_ABS_MIN,
            "rel_min": _COMPUTE_AVG_COMPONENT_REL_MIN,
        },
        "p99_total": {
            "abs_min_ms": _COMPUTE_P99_TOTAL_ABS_MIN,
            "rel_min": _COMPUTE_P99_TOTAL_REL_MIN,
        },
        "p99_component": {
            "abs_min_ms": _COMPUTE_P99_COMPONENT_ABS_MIN,
            "rel_min": _COMPUTE_P99_COMPONENT_REL_MIN,
        },
    }
    notable_avg_total = _is_notable_delta(
        deltas["bot_profile_total_ms_per_tick"],
        abs_min=_COMPUTE_AVG_TOTAL_ABS_MIN,
        rel_min=_COMPUTE_AVG_TOTAL_REL_MIN,
    )
    notable_avg_components = any(
        _is_notable_delta(
            deltas[name],
            abs_min=_COMPUTE_AVG_COMPONENT_ABS_MIN,
            rel_min=_COMPUTE_AVG_COMPONENT_REL_MIN,
        )
        for name in (
            "bot_profile_passive_ms_per_tick",
            "bot_profile_active_ms_per_tick",
            "bot_profile_query_ms_per_tick",
            "bot_profile_update_ms_per_tick",
        )
    )
    notable_p99_total = _is_notable_delta(
        deltas["bot_profile_total_ms_per_tick_p99"],
        abs_min=_COMPUTE_P99_TOTAL_ABS_MIN,
        rel_min=_COMPUTE_P99_TOTAL_REL_MIN,
    )
    notable_p99_components = any(
        _is_notable_delta(
            deltas[name],
            abs_min=_COMPUTE_P99_COMPONENT_ABS_MIN,
            rel_min=_COMPUTE_P99_COMPONENT_REL_MIN,
        )
        for name in (
            "bot_profile_query_ms_per_tick_p99",
            "bot_profile_update_ms_per_tick_p99",
        )
    )
    notable_avg = bool(notable_avg_total or notable_avg_components)
    notable_p99 = bool(notable_p99_total or notable_p99_components)
    notable_any = bool(notable_avg or notable_p99)

    return {
        "baseline": b,
        "candidate": c,
        "deltas": deltas,
        "thresholds": thresholds,
        "notable_avg": notable_avg,
        "notable_p99": notable_p99,
        "notable_any": notable_any,
    }


def _fmt_delta(delta: dict[str, float | None], scale_rel: bool = True) -> str:
    base = delta.get("baseline")
    cand = delta.get("candidate")
    d_abs = delta.get("delta_abs")
    d_rel = delta.get("delta_rel")
    if base is None or cand is None or d_abs is None or d_rel is None:
        return "n/a"
    if d_rel == float("inf"):
        rel_txt = "+inf"
    else:
        rel_txt = f"{(100.0 * float(d_rel)):+.1f}%" if scale_rel else f"{float(d_rel):+.3f}"
    return f"{float(base):.3f}->{float(cand):.3f} ({float(d_abs):+.3f}, {rel_txt})"


def _print_compute_block(
    label: str,
    *,
    compare: dict[str, Any],
    notable_regression: bool,
    gating: bool,
) -> dict[str, Any]:
    print(f"\n# compute_{label}")
    baseline = dict(compare.get("baseline") or {})
    candidate = dict(compare.get("candidate") or {})
    deltas = dict(compare.get("deltas") or {})
    b_available = bool(baseline.get("available", False))
    c_available = bool(candidate.get("available", False))
    print(f"available: baseline={b_available} candidate={c_available}")
    if not (b_available and c_available):
        print("note: compute compare unavailable (profiling was disabled or missing for one side).")
        return {
            "available": False,
            "notable_regression": False,
            "notable_scope": ("global_gate" if gating else "observation_only"),
            **compare,
        }

    print(
        "profiled_runs: "
        f"{_to_int(baseline.get('runs_profiled'), 0)}->{_to_int(candidate.get('runs_profiled'), 0)} "
        f"ticks={_to_int(baseline.get('ticks_total'), 0)}->{_to_int(candidate.get('ticks_total'), 0)}"
    )
    print(
        "avg_ms_per_tick(total/passive/active/query/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_passive_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_active_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_query_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_update_ms_per_tick') or {}))}"
    )
    print(
        "p99_ms_per_tick(total/query/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick_p99') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_query_ms_per_tick_p99') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_update_ms_per_tick_p99') or {}))}"
    )
    print(
        "p90_ms_per_tick(total/query/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick_p90') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_query_ms_per_tick_p90') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_update_ms_per_tick_p90') or {}))}"
    )
    if notable_regression:
        scope_txt = "global (gating)" if gating else "observation-only (non-gating)"
        print(f"notable_compute_regression: {scope_txt}")
    return {
        "available": True,
        "notable_regression": bool(notable_regression),
        "notable_scope": ("global_gate" if gating else "observation_only"),
        **compare,
    }


def _run_command(cmd: list[str]) -> tuple[int, str]:
    print("# run")
    print(" ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = str(proc.stdout or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return int(proc.returncode), output


def _load_or_run(
    *,
    commit: str,
    stem: str,
    mode: str,
    selectors: list[str],
    bot: str,
    workers: int | None,
    eval_mode: str,
    bot_profile_enabled: bool,
    bot_profile_interval_s: float | None,
    bot_profile_log_lines: bool,
    results_root: Path,
    reuse: bool,
    allow_run: bool,
) -> tuple[Path, Path, Path, bool]:
    out_dir = results_root / commit
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    meta_path = out_dir / f"{stem}.meta.json"

    expected_meta = {
        "mode": mode,
        "selectors": selectors,
        "bot": bot,
        "workers": (None if workers is None else int(workers)),
        "eval_mode": eval_mode,
        "bot_profile_enabled": bool(bot_profile_enabled),
        "bot_profile_interval_s": (
            None if bot_profile_interval_s is None else float(bot_profile_interval_s)
        ),
        "bot_profile_log_lines": bool(bot_profile_log_lines),
    }
    if reuse and json_path.exists() and csv_path.exists() and meta_path.exists():
        try:
            existing = _load_json(meta_path)
            if all(existing.get(k) == v for k, v in expected_meta.items()):
                print(f"# cache hit: {json_path}")
                return json_path, csv_path, meta_path, True
        except Exception:
            pass

    if not allow_run:
        raise SystemExit(
            f"Missing cache for commit {commit}: {json_path.name}. "
            "Run this pack from that commit once to seed cache."
        )

    cmd = build_bench_command(
        selectors=selectors,
        bot=bot,
        workers=workers,
        eval_mode=eval_mode,
        json_path=str(json_path),
        csv_path=str(csv_path),
        bot_profile_enabled=bool(bot_profile_enabled),
        bot_profile_interval_s=bot_profile_interval_s,
        bot_profile_log_lines=bool(bot_profile_log_lines),
    )
    code, output = _run_command(cmd)
    if code not in (0, 1):
        worker_error_markers = (
            "Batch workers unavailable",
            "refusing implicit sequential fallback",
        )
        if any(marker in output for marker in worker_error_markers):
            raise SystemExit(
                "Benchmark aborted: parallel workers are unavailable and sequential fallback is disabled.\n"
                "Please resolve process/worker support on this machine, or rerun intentionally with --workers 1."
            )
        raise SystemExit(f"Benchmark command failed with exit code {code}")
    if not json_path.exists():
        raise SystemExit(f"Expected benchmark JSON not found: {json_path}")
    if not csv_path.exists():
        raise SystemExit(f"Expected benchmark CSV not found: {csv_path}")

    payload = {
        **expected_meta,
        "commit": commit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "bench_exit_code": int(code),
    }
    _write_json(meta_path, payload)
    return json_path, csv_path, meta_path, False


def _print_compare(
    *,
    baseline_commit: str,
    candidate_commit: str,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    level_policy: dict[str, str],
    bot: str,
    eval_mode: str,
    crash_detail_limit: int = 8,
) -> dict[str, Any]:
    def _summary_block(
        label: str,
        *,
        baseline_block: dict[str, Any],
        candidate_block: dict[str, Any],
        crash_block: dict[str, list[dict[str, Any]]],
        crash_notable: bool,
    ) -> dict[str, Any]:
        b = _extract_summary_metrics(baseline_block)
        c = _extract_summary_metrics(candidate_block)
        use_success_primary = b["fuel_success_count"] > 0 and c["fuel_success_count"] > 0
        primary_fuel_b = b["fuel_mean_success"] if use_success_primary else b["fuel_mean_all"]
        primary_fuel_c = c["fuel_mean_success"] if use_success_primary else c["fuel_mean_all"]
        primary_fuel_dist_b = (
            b["fuel_per_distance_mean_success"] if use_success_primary else b["fuel_per_distance_mean_all"]
        )
        primary_fuel_dist_c = (
            c["fuel_per_distance_mean_success"] if use_success_primary else c["fuel_per_distance_mean_all"]
        )
        primary_basis = "success_only" if use_success_primary else "all_runs"

        print(f"\n# compare_{label}")
        print(f"runs: {int(b['runs'])} -> {int(c['runs'])}")
        print(
            "success_rate: "
            f"{b['success_rate']:.3f} -> {c['success_rate']:.3f} "
            f"(delta {c['success_rate'] - b['success_rate']:+.3f})"
        )
        print(f"crashed: {int(b['crashed'])} -> {int(c['crashed'])} (delta {int(c['crashed'] - b['crashed']):+d})")
        print(
            f"fuel_mean_primary[{primary_basis}]: "
            f"{primary_fuel_b:.3f} -> {primary_fuel_c:.3f} "
            f"(delta {primary_fuel_c - primary_fuel_b:+.3f})"
        )
        print(
            f"fuel_per_distance_mean_primary[{primary_basis}]: "
            f"{primary_fuel_dist_b:.4f} -> {primary_fuel_dist_c:.4f} "
            f"(delta {primary_fuel_dist_c - primary_fuel_dist_b:+.4f})"
        )
        if b["fuel_success_count"] <= 0 or c["fuel_success_count"] <= 0:
            print(
                "warning: success-only fuel aggregate unavailable for one side; "
                "primary fuel basis fell back to all-runs."
            )
        print(
            "fuel_mean_success: "
            f"{b['fuel_mean_success']:.3f} -> {c['fuel_mean_success']:.3f} "
            f"(delta {c['fuel_mean_success'] - b['fuel_mean_success']:+.3f}; "
            f"counts {int(b['fuel_success_count'])}->{int(c['fuel_success_count'])})"
        )
        print(
            "fuel_mean_all: "
            f"{b['fuel_mean_all']:.3f} -> {c['fuel_mean_all']:.3f} "
            f"(delta {c['fuel_mean_all'] - b['fuel_mean_all']:+.3f})"
        )
        print(
            "fuel_per_distance_mean_all: "
            f"{b['fuel_per_distance_mean_all']:.4f} -> {c['fuel_per_distance_mean_all']:.4f} "
            f"(delta {c['fuel_per_distance_mean_all'] - b['fuel_per_distance_mean_all']:+.4f})"
        )
        print(
            "new_crashes: "
            f"{len(crash_block['new_crashes'])} | resolved_crashes: {len(crash_block['resolved_crashes'])} "
            f"| candidate_crashes: {len(crash_block['candidate_crashes'])}"
        )
        if crash_notable:
            print(
                f"notable_regression: introduced {len(crash_block['new_crashes'])} "
                f"new crashes vs baseline ({label})"
            )
        return {
            "summary_baseline": b,
            "summary_candidate": c,
            "summary_delta": {
                "success_rate": c["success_rate"] - b["success_rate"],
                "crashed": c["crashed"] - b["crashed"],
                "fuel_basis_primary": primary_basis,
                "fuel_mean_primary": primary_fuel_c - primary_fuel_b,
                "fuel_per_distance_mean_primary": primary_fuel_dist_c - primary_fuel_dist_b,
                "fuel_mean_success": c["fuel_mean_success"] - b["fuel_mean_success"],
                "fuel_per_distance_mean_success": (
                    c["fuel_per_distance_mean_success"] - b["fuel_per_distance_mean_success"]
                ),
                "fuel_mean_all": c["fuel_mean_all"] - b["fuel_mean_all"],
                "fuel_per_distance_mean_all": (
                    c["fuel_per_distance_mean_all"] - b["fuel_per_distance_mean_all"]
                ),
            },
        }

    def _print_crash_details(
        title: str,
        *,
        crash_block: dict[str, list[dict[str, Any]]],
    ) -> None:
        if not crash_block["new_crashes"]:
            return
        print(f"\n# {title}")
        for item in crash_block["new_crashes"][: max(0, int(crash_detail_limit))]:
            print(
                f"{item['level']}:{item['scenario']}:{item['seed']} "
                f"baseline={item['baseline_state']} -> candidate={item['candidate_state']} "
                f"failure={item['candidate_failure_mode']}"
            )
            candidate_metrics = dict(item.get("candidate_metrics") or {})
            baseline_metrics = dict(item.get("baseline_metrics") or {})
            print(
                "  candidate_metrics: "
                f"time={_to_float(candidate_metrics.get('time'), 0.0):.2f} "
                f"fuel={_to_float(candidate_metrics.get('fuel_consumed'), 0.0):.3f} "
                f"setup_dx={_to_float(candidate_metrics.get('zem_setup_gate_projected_dx'), 0.0):.3f} "
                f"terminal_dx={_to_float(candidate_metrics.get('zem_terminal_gate_projected_dx'), 0.0):.3f}"
            )
            if baseline_metrics:
                print(
                    "  baseline_metrics: "
                    f"state={baseline_metrics.get('state')} "
                    f"failure={baseline_metrics.get('failure_mode')} "
                    f"time={_to_float(baseline_metrics.get('time'), 0.0):.2f} "
                    f"fuel={_to_float(baseline_metrics.get('fuel_consumed'), 0.0):.3f}"
                )
            repro = dict(item.get("repro") or {})
            if repro.get("plot"):
                print(f"  plot: {repro['plot']}")
            if repro.get("sim_trace"):
                print(f"  sim:  {repro['sim_trace']}")
            if repro.get("sim_profile"):
                print(f"  prof: {repro['sim_profile']}")

    baseline_parts = _partition_payload_by_policy(
        baseline_payload,
        level_policy=level_policy,
    )
    candidate_parts = _partition_payload_by_policy(
        candidate_payload,
        level_policy=level_policy,
    )
    crash_global = _crash_deltas(
        baseline_payload=baseline_parts["global"],
        candidate_payload=candidate_parts["global"],
        bot=bot,
        eval_mode=eval_mode,
    )
    crash_observation = _crash_deltas(
        baseline_payload=baseline_parts["observation"],
        candidate_payload=candidate_parts["observation"],
        bot=bot,
        eval_mode=eval_mode,
    )

    print("\n# compare")
    print(f"baseline={baseline_commit} candidate={candidate_commit}")
    print(
        "policy_counts: "
        f"normal={len(_payload_records(candidate_parts['global']))} "
        f"observe_or_excluded={len(_payload_records(candidate_parts['observation']))}"
    )

    global_summary = _summary_block(
        "global",
        baseline_block=baseline_parts["global"],
        candidate_block=candidate_parts["global"],
        crash_block=crash_global,
        crash_notable=len(crash_global["new_crashes"]) > 0,
    )
    observation_summary = _summary_block(
        "observation",
        baseline_block=baseline_parts["observation"],
        candidate_block=candidate_parts["observation"],
        crash_block=crash_observation,
        crash_notable=False,
    )
    compute_global = _compute_compare(
        baseline_payload=baseline_parts["global"],
        candidate_payload=candidate_parts["global"],
    )
    compute_observation = _compute_compare(
        baseline_payload=baseline_parts["observation"],
        candidate_payload=candidate_parts["observation"],
    )
    compute_global_notable = bool(compute_global.get("notable_any", False))
    compute_observation_notable = bool(compute_observation.get("notable_any", False))
    compute_global_summary = _print_compute_block(
        "global",
        compare=compute_global,
        notable_regression=compute_global_notable,
        gating=True,
    )
    compute_observation_summary = _print_compute_block(
        "observation",
        compare=compute_observation,
        notable_regression=compute_observation_notable,
        gating=False,
    )

    _print_crash_details(
        "crash_regressions_global",
        crash_block=crash_global,
    )
    _print_crash_details(
        "crash_regressions_observation",
        crash_block=crash_observation,
    )
    if crash_observation["new_crashes"]:
        print(
            "note: observation-only/excluded crash regressions were detected and reported, "
            "but do not mark global regression status."
        )
    if crash_global["candidate_crashes"] and not crash_global["new_crashes"]:
        print(
            "note: candidate still has global crashes, but none are newly introduced "
            "relative to baseline."
        )

    deltas_global = _scenario_regressions(
        baseline_parts["global"],
        candidate_parts["global"],
    )
    if deltas_global:
        print("\n# worst_scenarios_global")
        for row in deltas_global[:8]:
            print(
                f"{row['scenario']}: "
                f"delta_success_rate={float(row['delta_success_rate']):+.3f} "
                f"delta_fuel_mean={float(row['delta_fuel_mean']):+.3f} "
                f"basis={row['fuel_basis']}"
            )

    deltas_observation = _scenario_regressions(
        baseline_parts["observation"],
        candidate_parts["observation"],
    )
    if deltas_observation:
        print("\n# worst_scenarios_observation")
        for row in deltas_observation[:8]:
            print(
                f"{row['scenario']}: "
                f"delta_success_rate={float(row['delta_success_rate']):+.3f} "
                f"delta_fuel_mean={float(row['delta_fuel_mean']):+.3f} "
                f"basis={row['fuel_basis']}"
            )

    crash_global_notable = len(crash_global["new_crashes"]) > 0
    global_notable = bool(crash_global_notable or compute_global_notable)
    return {
        "baseline_commit": baseline_commit,
        "candidate_commit": candidate_commit,
        "policy_context": {
            "effective_level_policy": dict(level_policy),
            "levels_observe_or_excluded": sorted(
                level_name
                for level_name, policy in level_policy.items()
                if policy in {"observe_only", "excluded"}
            ),
        },
        "global": {
            **global_summary,
            "crash": crash_global,
            "compute": compute_global_summary,
            "notable_regression": global_notable,
            "worst_scenarios": deltas_global[:20],
        },
        "observation": {
            **observation_summary,
            "crash": crash_observation,
            "compute": compute_observation_summary,
            "notable_regression": False,
            "worst_scenarios": deltas_observation[:20],
        },
        "notable_regression": global_notable,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run cached Pylander benchmarks with optional baseline compare")
    ap.add_argument("--mode", choices=("smoke", "quick", "full", "focused"), required=True)
    ap.add_argument("--seed-spec", default=None, help="Override default seed range, e.g. 0-9")
    ap.add_argument("--selectors", nargs="*", default=[], help="Focused selectors")
    ap.add_argument(
        "--exclude-levels",
        nargs="*",
        default=[],
        help="Levels to exclude from auto packs (csv or repeated)",
    )
    ap.add_argument(
        "--observe-only-levels",
        nargs="*",
        default=[],
        help="Levels to keep as observation-only (csv or repeated)",
    )
    ap.add_argument("--bot", default="zem_zev")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--eval-mode", default="auto", choices=("auto", "focused", "full"))
    ap.add_argument(
        "--bot-profile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable bot compute profiling in benchmark runs (default: on)",
    )
    ap.add_argument(
        "--bot-profile-interval-s",
        type=float,
        default=None,
        help="Profiler report interval in seconds (when profiler logs are enabled)",
    )
    ap.add_argument(
        "--bot-profile-logs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable periodic profiler logs in benchmark output (default: off)",
    )
    ap.add_argument("--baseline-ref", default=None, help="Git ref to compare against (e.g. main)")
    ap.add_argument("--results-dir", default="outputs/benchmarks")
    ap.add_argument("--no-reuse", action="store_true", help="Ignore cache and rerun current commit pack")
    ap.add_argument("--crash-detail-limit", type=int, default=8)
    args = ap.parse_args()

    try:
        pack: ResolvedSelectorPack = build_selectors(
            mode=args.mode,
            seed_spec=args.seed_spec,
            focused_selectors=args.selectors,
            exclude_levels=args.exclude_levels,
            observe_only_levels=args.observe_only_levels,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    current_commit = _workspace_key()
    baseline_commit = _git_rev_parse(args.baseline_ref) if args.baseline_ref else None
    stem = _selector_pack_stem(
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        eval_mode=args.eval_mode,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=(
            None if args.bot_profile_interval_s is None else max(0.25, float(args.bot_profile_interval_s))
        ),
        bot_profile_log_lines=bool(args.bot_profile_logs),
    )
    results_root = (_REPO_ROOT / args.results_dir).resolve()

    cand_json, cand_csv, cand_meta, cand_cached = _load_or_run(
        commit=current_commit,
        stem=stem,
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        workers=args.workers,
        eval_mode=args.eval_mode,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=(
            None if args.bot_profile_interval_s is None else max(0.25, float(args.bot_profile_interval_s))
        ),
        bot_profile_log_lines=bool(args.bot_profile_logs),
        results_root=results_root,
        reuse=not args.no_reuse,
        allow_run=True,
    )
    print(f"\n# candidate\ncommit={current_commit}\njson={cand_json}\ncsv={cand_csv}\nmeta={cand_meta}\ncached={cand_cached}")
    print(
        "\n# policy\n"
        f"included_levels={','.join(pack.included_levels)}\n"
        f"excluded_levels_effective={','.join(pack.excluded_levels_effective)}\n"
        f"observe_only_levels_effective={','.join(pack.observe_only_levels_effective)}"
    )

    if not baseline_commit:
        return

    base_json, base_csv, base_meta, base_cached = _load_or_run(
        commit=baseline_commit,
        stem=stem,
        mode=args.mode,
        selectors=pack.selectors,
        bot=args.bot,
        workers=args.workers,
        eval_mode=args.eval_mode,
        bot_profile_enabled=bool(args.bot_profile),
        bot_profile_interval_s=(
            None if args.bot_profile_interval_s is None else max(0.25, float(args.bot_profile_interval_s))
        ),
        bot_profile_log_lines=bool(args.bot_profile_logs),
        results_root=results_root,
        reuse=True,
        allow_run=(baseline_commit == current_commit),
    )
    print(f"\n# baseline\ncommit={baseline_commit}\njson={base_json}\ncsv={base_csv}\nmeta={base_meta}\ncached={base_cached}")

    candidate_payload = _load_json(cand_json)
    baseline_payload = _load_json(base_json)
    compare = _print_compare(
        baseline_commit=baseline_commit,
        candidate_commit=current_commit,
        baseline_payload=baseline_payload,
        candidate_payload=candidate_payload,
        level_policy=pack.effective_level_policy,
        bot=args.bot,
        eval_mode=args.eval_mode,
        crash_detail_limit=max(0, int(args.crash_detail_limit)),
    )
    policy_digest_payload = json.dumps(
        {
            "policy": pack.effective_level_policy,
            "excluded": pack.excluded_levels_effective,
            "observe_only": pack.observe_only_levels_effective,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    policy_digest = hashlib.sha1(policy_digest_payload.encode("utf-8")).hexdigest()[:8]
    compare_token = _sanitize_token(f"compare_vs_{baseline_commit}_{policy_digest}")
    compare_path = cand_json.with_name(f"{cand_json.stem}.{compare_token}.json")
    _write_json(compare_path, compare)
    print(f"\n# compare_report\njson={compare_path}")


if __name__ == "__main__":
    main()
