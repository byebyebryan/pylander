from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.eval_schema import (
    ARRIVAL_RESULT_FIELDS,
    BOT_PROFILE_RESULT_FIELDS,
    EFFICIENCY_METRIC_FIELDS,
    SETUP_GATE_RESULT_FIELDS,
    SETUP_GOAL_RESULT_FIELDS,
    TRACE_METRIC_RESULT_FIELDS,
)
from core.selector_codec import render_record_selector

_DEFAULT_FLOAT_RESULT_FIELDS: tuple[str, ...] = (
    "time",
    "credits",
    "fuel",
    "fuel_remaining",
    "score",
    "distance_flown",
    "avg_speed",
    "fuel_consumed",
    "fuel_per_distance",
    "overdrive_time",
    "overdrive_fraction",
    "overdrive_excess",
)

_OPTIONAL_FLOAT_RESULT_FIELDS: tuple[str, ...] = (
    "landing_offset",
    "path_efficiency",
    "time_to_first_land",
    "spawn_to_target_distance",
    "trace_sample_period_s",
    *tuple(
        field
        for field in SETUP_GOAL_RESULT_FIELDS
        if field not in {"boost_goal_done", "boost_goal_has_target_y_solution"}
    ),
    *tuple(
        field
        for field in SETUP_GATE_RESULT_FIELDS
        if field not in {"boost_cutoff_done", "boost_cutoff_has_target_y_solution"}
    ),
    *tuple(field for field in BOT_PROFILE_RESULT_FIELDS if field != "bot_profile_enabled"),
    *TRACE_METRIC_RESULT_FIELDS,
)

_OPTIONAL_BOOL_RESULT_FIELDS: tuple[str, ...] = (
    "eval_early_end",
    "boost_goal_done",
    "boost_goal_has_target_y_solution",
    "boost_cutoff_done",
    "boost_cutoff_has_target_y_solution",
    *tuple(field for field in ARRIVAL_RESULT_FIELDS if field.endswith("_arrived")),
    "bot_profile_enabled",
)

_PASSTHROUGH_RESULT_FIELDS: tuple[str, ...] = (
    "eval_end_reason",
    *tuple(field for field in ARRIVAL_RESULT_FIELDS if not field.endswith("_arrived")),
    "trace_path",
    "trace_rel_path",
    "trace_preview_path",
    "trace_preview_rel_path",
    "trace_schema_version",
    "trace_snapshot_count",
    "trace_event_count",
    "trace_control_log_count",
    "trace_detail",
    "run_key",
    "run_instance_id",
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    clamped = max(0.0, min(1.0, p))
    idx = (len(sorted_values) - 1) * clamped
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _metric_summary(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [
        float(record[field])
        for record in records
        if isinstance(record.get(field), (int, float))
    ]
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stddev": 0.0,
        }
    values.sort()
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return {
        "count": count,
        "mean": mean,
        "median": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "min": values[0],
        "max": values[-1],
        "stddev": variance**0.5,
    }


def _efficiency_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {field: _metric_summary(records, field) for field in EFFICIENCY_METRIC_FIELDS}


def normalize_run_result(
    *,
    bot_name: str,
    level_name: str,
    scenario: str | None,
    seed: int | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    state = str(result.get("state", "unknown"))
    landing_count = int(result.get("landing_count", 0) or 0)
    crash_count = int(result.get("crash_count", 0) or 0)
    success_raw = result.get("success")
    if isinstance(success_raw, bool):
        success = success_raw
    elif isinstance(success_raw, (int, float)):
        success = bool(success_raw)
    else:
        success = state == "landed"
    failure_mode_raw = result.get("failure_mode")
    if isinstance(failure_mode_raw, str) and failure_mode_raw.strip():
        failure_mode = failure_mode_raw.strip()
    else:
        failure_mode = "none" if success else state
    eval_goal = str(result.get("eval_goal") or "landing")
    record = {
        "bot": bot_name,
        "level": level_name,
        "scenario": scenario,
        "seed": seed,
        "state": state,
        "landing_count": landing_count,
        "crash_count": crash_count,
        "success": success,
        "failure_mode": failure_mode,
        "eval_goal": eval_goal,
    }
    record["fuel_remaining"] = _to_float(
        result.get("fuel_remaining", result.get("fuel", 0.0)),
        0.0,
    )
    for field in _DEFAULT_FLOAT_RESULT_FIELDS:
        if field == "fuel_remaining":
            continue
        record[field] = _to_float(result.get(field, 0.0), 0.0)
    for field in _OPTIONAL_FLOAT_RESULT_FIELDS:
        record[field] = _to_optional_float(result.get(field))
    for field in _OPTIONAL_BOOL_RESULT_FIELDS:
        record[field] = _to_optional_bool(result.get(field))
    for field in _PASSTHROUGH_RESULT_FIELDS:
        record[field] = result.get(field)
    for key, value in result.items():
        if not isinstance(key, str):
            continue
        if not (key.startswith("scenario_") or key.startswith("bot_")):
            continue
        if key in record:
            continue
        if key.startswith("bot_") and not key.endswith("_done"):
            numeric_value = _to_optional_float(value)
            if numeric_value is not None:
                record[key] = numeric_value
                continue
        if key.startswith("bot_") and key.endswith("_done"):
            bool_value = _to_optional_bool(value)
            if bool_value is not None:
                record[key] = bool_value
                continue
        if isinstance(value, (int, float, str, bool)) or value is None:
            record[key] = value
    return record


def _summary_bucket() -> dict[str, Any]:
    return {
        "runs": 0,
        "successes": 0,
        "landed": 0,
        "crashed": 0,
        "out_of_fuel": 0,
        "flying": 0,
        "other": 0,
        "success_rate": 0.0,
        "_records": [],
    }


def _finalize_summary_bucket(item: dict[str, Any]) -> None:
    runs = int(item["runs"])
    item["success_rate"] = (item["successes"] / runs) if runs > 0 else 0.0
    item_records = item.pop("_records")
    item_success = [record for record in item_records if record.get("success", False)]
    item["efficiency_success"] = _efficiency_summary(item_success)
    item["efficiency_all"] = _efficiency_summary(item_records)


def aggregate_eval_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    successes = sum(1 for r in records if bool(r.get("success", False)))
    landed = sum(1 for r in records if r.get("state") == "landed")
    crashes = sum(1 for r in records if r.get("state") == "crashed")
    out_of_fuel = sum(1 for r in records if r.get("state") == "out_of_fuel")
    flying = sum(1 for r in records if r.get("state") == "flying")
    other = total - landed - crashes - out_of_fuel - flying
    success_rate = (successes / total) if total > 0 else 0.0

    by_scenario: dict[str, dict[str, Any]] = {}
    by_selector: dict[str, dict[str, Any]] = {}
    for record in records:
        scenario_name = str(record.get("scenario") or "default")
        scenario_item = by_scenario.setdefault(scenario_name, _summary_bucket())
        selector_key = render_record_selector(record, include_seed=False)
        selector_item = by_selector.setdefault(selector_key, _summary_bucket())
        for item in (scenario_item, selector_item):
            item["runs"] += 1
            if bool(record.get("success", False)):
                item["successes"] += 1
            item["_records"].append(record)
            state = record.get("state")
            if state in ("landed", "crashed", "out_of_fuel", "flying"):
                item[state] += 1
            else:
                item["other"] += 1

    successful_records = [record for record in records if record.get("success", False)]
    for item in by_scenario.values():
        _finalize_summary_bucket(item)
    for item in by_selector.values():
        _finalize_summary_bucket(item)

    return {
        "runs": total,
        "successes": successes,
        "landed": landed,
        "crashed": crashes,
        "out_of_fuel": out_of_fuel,
        "flying": flying,
        "other": other,
        "success_rate": success_rate,
        "efficiency_success": _efficiency_summary(successful_records),
        "efficiency_all": _efficiency_summary(records),
        "by_scenario": by_scenario,
        "by_selector": by_selector,
    }


def _sanitize_slug(parts: list[str]) -> str:
    out: list[str] = []
    for part in parts:
        clean = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in part)
        clean = clean.strip("_")
        if clean:
            out.append(clean)
    return "_".join(out) if out else "eval"


def default_artifact_path(
    *,
    kind: str,
    level_name: str,
    bot_name: str,
    seeds: list[int],
    scenarios: list[str],
    directory: str | Path = "outputs",
) -> Path:
    seed_tag = f"{min(seeds)}-{max(seeds)}" if seeds else "none"
    scenario_tag = ",".join(sorted(scenarios)) if scenarios else "default"
    digest_payload = f"{level_name}|{bot_name}|{seed_tag}|{scenario_tag}"
    digest = hashlib.sha1(digest_payload.encode("utf-8")).hexdigest()[:8]
    stem = _sanitize_slug(["eval", level_name, bot_name, seed_tag, digest])
    return Path(directory) / f"{stem}.{kind}"


_COLLISION_SAFE_PATH_LIMIT = 10_000


def collision_safe_path(path: str | Path) -> Path:
    base = Path(path)
    if not base.exists():
        return base
    for idx in range(1, _COLLISION_SAFE_PATH_LIMIT + 1):
        candidate = base.with_name(f"{base.stem}-{idx}{base.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(
        f"collision_safe_path: exceeded {_COLLISION_SAFE_PATH_LIMIT} candidates for {base}"
    )


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    out = collision_safe_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out
