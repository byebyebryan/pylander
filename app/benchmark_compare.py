from __future__ import annotations

from typing import Any, Mapping

from core.eval import aggregate_eval_records
from core.selector_codec import render_record_selector
from utils.botmetrics import bot_metric_key

_COMPUTE_FIELDS: tuple[str, ...] = (
    "bot_profile_total_ms_per_tick",
    "bot_profile_passive_ms_per_tick",
    "bot_profile_update_ms_per_tick",
    "bot_profile_total_ms_per_tick_p90",
    "bot_profile_total_ms_per_tick_p99",
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
        "fuel_per_distance_mean_success": _mean(
            efficiency_success, "fuel_per_distance"
        ),
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


def _selector_summary_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary = aggregate_eval_records(_payload_records(payload))
    rows = dict(summary.get("by_selector") or {})
    out: dict[str, dict[str, Any]] = {}
    for selector, row in rows.items():
        out[str(selector)] = {
            "success_rate": float(row.get("success_rate", 0.0) or 0.0),
            "efficiency_success": dict(row.get("efficiency_success") or {}),
            "efficiency_all": dict(row.get("efficiency_all") or {}),
        }
    return out


def _fuel_mean_from_summary(row: dict[str, Any]) -> tuple[float, int, float]:
    eff_success = dict(row.get("efficiency_success") or {})
    eff_all = dict(row.get("efficiency_all") or {})
    success_stats = dict(eff_success.get("fuel_consumed") or {})
    all_stats = dict(eff_all.get("fuel_consumed") or {})
    success_mean = float(success_stats.get("mean", 0.0) or 0.0)
    success_count = int(success_stats.get("count", 0) or 0)
    all_mean = float(all_stats.get("mean", 0.0) or 0.0)
    return success_mean, success_count, all_mean


def _record_level_policy(
    record: dict[str, Any],
    *,
    level_policy: Mapping[str, str],
) -> str:
    level_name = str(record.get("level") or "").strip()
    token = str(level_policy.get(level_name, "normal") or "normal").strip().lower()
    if token in {"observe_only", "excluded"}:
        return token
    return "normal"


def _partition_payload_by_policy(
    payload: dict[str, Any],
    *,
    level_policy: Mapping[str, str],
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


def run_diag(record: dict[str, Any], *, bot: str) -> dict[str, Any]:
    terminal_dx_key = bot_metric_key(bot, "terminal_entry_projected_dx")
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
        "boost_cutoff_projected_dx",
        terminal_dx_key,
    )
    out: dict[str, Any] = {}
    for key in keys:
        if key in record:
            out[key] = record.get(key)
    out["bot_terminal_entry_projected_dx_field"] = terminal_dx_key
    out["bot_terminal_entry_projected_dx"] = record.get(terminal_dx_key)
    return out


def _records_by_key(
    payload: dict[str, Any],
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    out: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for rec_raw in payload.get("records") or []:
        if not isinstance(rec_raw, dict):
            continue
        rec = dict(rec_raw)
        level = str(rec.get("level") or "").strip()
        scenario = str(rec.get("scenario") or "").strip()
        eval_goal = str(rec.get("eval_goal") or "landing").strip().lower()
        if not eval_goal:
            eval_goal = "landing"
        seed = _to_int(rec.get("seed"), 0)
        if not level:
            continue
        out[(level, scenario, eval_goal, seed)] = rec
    return out


def _make_repro_commands(
    record: dict[str, Any],
    *,
    bot: str,
) -> dict[str, str]:
    selector = render_record_selector(record)
    return {
        "plot": f"uv run python main.py plot {selector} --bot {bot}",
        "sim_trace": f"uv run python main.py sim {selector} --bot {bot} --freq 1",
        "sim_profile": (
            f"PYLANDER_BOT_PROFILE=1 uv run python main.py sim {selector} "
            f"--bot {bot} --freq 1"
        ),
    }


def _crash_deltas(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    bot: str,
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
                "eval_goal": key[2],
                "seed": key[3],
                "candidate_state": c_state,
                "baseline_state": b_state,
                "candidate_failure_mode": c_rec.get("failure_mode"),
                "baseline_failure_mode": b_rec.get("failure_mode"),
                "candidate_fuel_consumed": c_rec.get("fuel_consumed"),
                "candidate_time": c_rec.get("time"),
                "candidate_metrics": run_diag(c_rec, bot=bot),
                "baseline_metrics": run_diag(b_rec, bot=bot),
                "repro": _make_repro_commands(c_rec, bot=bot),
            }
            candidate_crashes.append(entry)
            if b_state != "crashed":
                new_crashes.append(entry)
        elif b_state == "crashed":
            resolved_crashes.append(
                {
                    "level": key[0],
                    "scenario": key[1],
                    "eval_goal": key[2],
                    "seed": key[3],
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


def scenario_regressions(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, float | str]]:
    b = _selector_summary_rows(baseline)
    c = _selector_summary_rows(candidate)
    names = sorted(set(b) | set(c))
    out: list[dict[str, float | str]] = []
    for name in names:
        b_row = dict(b.get(name) or {})
        c_row = dict(c.get(name) or {})
        b_sr = float(b_row.get("success_rate", 0.0) or 0.0)
        c_sr = float(c_row.get("success_rate", 0.0) or 0.0)
        b_fuel_success, b_fuel_success_n, b_fuel_all = _fuel_mean_from_summary(b_row)
        c_fuel_success, c_fuel_success_n, c_fuel_all = _fuel_mean_from_summary(c_row)
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
    out.sort(
        key=lambda row: (
            float(row["delta_success_rate"]),
            -float(row["delta_fuel_mean"]),
        )
    )
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
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta_abs": None,
            "delta_rel": None,
        }
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
        for name in ("bot_profile_update_ms_per_tick_p99",)
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
        rel_txt = (
            f"{(100.0 * float(d_rel)):+.1f}%" if scale_rel else f"{float(d_rel):+.3f}"
        )
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
        print(
            "note: compute compare unavailable (profiling was disabled or missing for one side)."
        )
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
        "avg_ms_per_tick(total/passive/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_passive_ms_per_tick') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_update_ms_per_tick') or {}))}"
    )
    print(
        "p99_ms_per_tick(total/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick_p99') or {}))} / "
        f"{_fmt_delta(dict(deltas.get('bot_profile_update_ms_per_tick_p99') or {}))}"
    )
    print(
        "p90_ms_per_tick(total/update): "
        f"{_fmt_delta(dict(deltas.get('bot_profile_total_ms_per_tick_p90') or {}))} / "
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


def print_compare(
    *,
    baseline_commit: str,
    candidate_commit: str,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    level_policy: Mapping[str, str],
    bot: str,
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
        use_success_primary = (
            b["fuel_success_count"] > 0 and c["fuel_success_count"] > 0
        )
        primary_fuel_b = (
            b["fuel_mean_success"] if use_success_primary else b["fuel_mean_all"]
        )
        primary_fuel_c = (
            c["fuel_mean_success"] if use_success_primary else c["fuel_mean_all"]
        )
        primary_fuel_dist_b = (
            b["fuel_per_distance_mean_success"]
            if use_success_primary
            else b["fuel_per_distance_mean_all"]
        )
        primary_fuel_dist_c = (
            c["fuel_per_distance_mean_success"]
            if use_success_primary
            else c["fuel_per_distance_mean_all"]
        )
        primary_basis = "success_only" if use_success_primary else "all_runs"

        print(f"\n# compare_{label}")
        print(f"runs: {int(b['runs'])} -> {int(c['runs'])}")
        print(
            "success_rate: "
            f"{b['success_rate']:.3f} -> {c['success_rate']:.3f} "
            f"(delta {c['success_rate'] - b['success_rate']:+.3f})"
        )
        print(
            f"crashed: {int(b['crashed'])} -> {int(c['crashed'])} (delta {int(c['crashed'] - b['crashed']):+d})"
        )
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
                "fuel_per_distance_mean_primary": primary_fuel_dist_c
                - primary_fuel_dist_b,
                "fuel_mean_success": c["fuel_mean_success"] - b["fuel_mean_success"],
                "fuel_per_distance_mean_success": (
                    c["fuel_per_distance_mean_success"]
                    - b["fuel_per_distance_mean_success"]
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
                f"boost_dx={_to_float(candidate_metrics.get('boost_cutoff_projected_dx'), 0.0):.3f} "
                f"terminal_dx={_to_float(candidate_metrics.get('bot_terminal_entry_projected_dx'), 0.0):.3f}"
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
    )
    crash_observation = _crash_deltas(
        baseline_payload=baseline_parts["observation"],
        candidate_payload=candidate_parts["observation"],
        bot=bot,
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

    deltas_global = scenario_regressions(
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

    deltas_observation = scenario_regressions(
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


__all__ = ["print_compare", "run_diag", "scenario_regressions"]
