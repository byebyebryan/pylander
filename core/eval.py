from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from core.eval_schema import EFFICIENCY_METRIC_FIELDS


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
        return {"count": 0, "mean": 0.0, "median": 0.0, "p90": 0.0}
    values.sort()
    count = len(values)
    return {
        "count": count,
        "mean": sum(values) / count,
        "median": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
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
    record = {
        "bot": bot_name,
        "level": level_name,
        "scenario": scenario,
        "seed": seed,
        "state": state,
        "time": _to_float(result.get("time", 0.0), 0.0),
        "landing_count": landing_count,
        "crash_count": crash_count,
        "credits": _to_float(result.get("credits", 0.0), 0.0),
        "fuel": _to_float(result.get("fuel", 0.0), 0.0),
        "fuel_remaining": _to_float(
            result.get("fuel_remaining", result.get("fuel", 0.0)),
            0.0,
        ),
        "score": _to_float(result.get("score", 0.0), 0.0),
        "distance_flown": _to_float(result.get("distance_flown", 0.0), 0.0),
        "landing_offset": _to_optional_float(result.get("landing_offset")),
        "avg_speed": _to_float(result.get("avg_speed", 0.0), 0.0),
        "fuel_consumed": _to_float(result.get("fuel_consumed", 0.0), 0.0),
        "fuel_per_distance": _to_float(result.get("fuel_per_distance", 0.0), 0.0),
        "overdrive_time": _to_float(result.get("overdrive_time", 0.0), 0.0),
        "overdrive_fraction": _to_float(result.get("overdrive_fraction", 0.0), 0.0),
        "overdrive_excess": _to_float(result.get("overdrive_excess", 0.0), 0.0),
        "path_efficiency": _to_optional_float(result.get("path_efficiency")),
        "time_to_first_land": _to_optional_float(result.get("time_to_first_land")),
        "spawn_to_target_distance": _to_optional_float(
            result.get("spawn_to_target_distance")
        ),
        "success": success,
        "failure_mode": failure_mode,
        "eval_mode": result.get("eval_mode"),
        "eval_phase": result.get("eval_phase"),
        "launch_arrived": _to_optional_bool(result.get("launch_arrived")),
        "launch_landed_site_uid": result.get("launch_landed_site_uid"),
        "climb_arrived": _to_optional_bool(result.get("climb_arrived")),
        "climb_landed_site_uid": result.get("climb_landed_site_uid"),
        "zem_setup_gate_done": _to_optional_bool(result.get("zem_setup_gate_done")),
        "zem_setup_gate_time": _to_optional_float(result.get("zem_setup_gate_time")),
        "zem_setup_gate_altitude": _to_optional_float(
            result.get("zem_setup_gate_altitude")
        ),
        "zem_setup_gate_projected_dx": _to_optional_float(
            result.get("zem_setup_gate_projected_dx")
        ),
        "zem_terminal_gate_done": _to_optional_bool(result.get("zem_terminal_gate_done")),
        "zem_terminal_gate_time": _to_optional_float(result.get("zem_terminal_gate_time")),
        "zem_terminal_gate_altitude": _to_optional_float(
            result.get("zem_terminal_gate_altitude")
        ),
        "zem_terminal_gate_projected_dx": _to_optional_float(
            result.get("zem_terminal_gate_projected_dx")
        ),
        "zem_solve_count": _to_optional_float(result.get("zem_solve_count")),
        "zem_solve_ms_mean": _to_optional_float(result.get("zem_solve_ms_mean")),
        "zem_solve_ms_p90": _to_optional_float(result.get("zem_solve_ms_p90")),
        "zem_fallback_frames": _to_optional_float(result.get("zem_fallback_frames")),
        "zem_peak_alt_over_target": _to_optional_float(
            result.get("zem_peak_alt_over_target")
        ),
        "zem_lateral_overshoot": _to_optional_float(result.get("zem_lateral_overshoot")),
        "zem_hover_time": _to_optional_float(result.get("zem_hover_time")),
        "zem_clearance_margin": _to_optional_float(result.get("zem_clearance_margin")),
        "zem_clearance_scale": _to_optional_float(result.get("zem_clearance_scale")),
        "zem_clearance_active": _to_optional_bool(result.get("zem_clearance_active")),
        "setup_phase_done": _to_optional_bool(result.get("setup_phase_done")),
        "setup_phase_time": _to_optional_float(result.get("setup_phase_time")),
        "setup_phase_altitude": _to_optional_float(result.get("setup_phase_altitude")),
        "setup_phase_projected_dx": _to_optional_float(
            result.get("setup_phase_projected_dx")
        ),
        "setup_phase_distance": _to_optional_float(result.get("setup_phase_distance")),
        "setup_phase_fuel_consumed": _to_optional_float(
            result.get("setup_phase_fuel_consumed")
        ),
        "setup_phase_fuel_per_distance": _to_optional_float(
            result.get("setup_phase_fuel_per_distance")
        ),
        "setup_phase_path_efficiency": _to_optional_float(
            result.get("setup_phase_path_efficiency")
        ),
        "coast_phase_done": _to_optional_bool(result.get("coast_phase_done")),
        "coast_phase_time": _to_optional_float(result.get("coast_phase_time")),
        "coast_phase_altitude": _to_optional_float(result.get("coast_phase_altitude")),
        "coast_phase_projected_dx": _to_optional_float(
            result.get("coast_phase_projected_dx")
        ),
        "coast_phase_distance": _to_optional_float(result.get("coast_phase_distance")),
        "coast_phase_fuel_consumed": _to_optional_float(
            result.get("coast_phase_fuel_consumed")
        ),
        "coast_phase_fuel_per_distance": _to_optional_float(
            result.get("coast_phase_fuel_per_distance")
        ),
        "coast_phase_path_efficiency": _to_optional_float(
            result.get("coast_phase_path_efficiency")
        ),
        "climb_phase_done": _to_optional_bool(result.get("climb_phase_done")),
        "climb_phase_time": _to_optional_float(result.get("climb_phase_time")),
        "climb_phase_altitude": _to_optional_float(result.get("climb_phase_altitude")),
        "climb_phase_projected_dx": _to_optional_float(
            result.get("climb_phase_projected_dx")
        ),
        "climb_phase_distance": _to_optional_float(result.get("climb_phase_distance")),
        "climb_phase_fuel_consumed": _to_optional_float(
            result.get("climb_phase_fuel_consumed")
        ),
        "climb_phase_fuel_per_distance": _to_optional_float(
            result.get("climb_phase_fuel_per_distance")
        ),
        "climb_phase_path_efficiency": _to_optional_float(
            result.get("climb_phase_path_efficiency")
        ),
    }
    for key, value in result.items():
        if not isinstance(key, str) or not key.startswith("scenario_"):
            continue
        if isinstance(value, (int, float, str, bool)) or value is None:
            record[key] = value
    if "plot_path" in result:
        record["plot_path"] = result.get("plot_path")
    if "plot_paths" in result:
        record["plot_paths"] = result.get("plot_paths")
    return record


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
    for record in records:
        key = str(record.get("scenario") or "default")
        item = by_scenario.setdefault(
            key,
            {
                "runs": 0,
                "successes": 0,
                "landed": 0,
                "crashed": 0,
                "out_of_fuel": 0,
                "flying": 0,
                "other": 0,
                "success_rate": 0.0,
                "_records": [],
            },
        )
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
        runs = int(item["runs"])
        item["success_rate"] = (item["successes"] / runs) if runs > 0 else 0.0
        item_records = item.pop("_records")
        item_success = [record for record in item_records if record.get("success", False)]
        item["efficiency_success"] = _efficiency_summary(item_success)
        item["efficiency_all"] = _efficiency_summary(item_records)

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


def collision_safe_path(path: str | Path) -> Path:
    base = Path(path)
    if not base.exists():
        return base
    idx = 1
    while True:
        candidate = base.with_name(f"{base.stem}-{idx}{base.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    out = collision_safe_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def write_csv_records(path: str | Path, records: list[dict[str, Any]]) -> Path:
    out = collision_safe_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames_set: set[str] = set()
    for record in records:
        fieldnames_set.update(record.keys())
    fieldnames = sorted(fieldnames_set)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    return out
