from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


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
    record = {
        "bot": bot_name,
        "level": level_name,
        "scenario": scenario,
        "seed": seed,
        "state": state,
        "time": float(result.get("time", 0.0) or 0.0),
        "landing_count": landing_count,
        "crash_count": crash_count,
        "credits": float(result.get("credits", 0.0) or 0.0),
        "fuel": float(result.get("fuel", 0.0) or 0.0),
        "score": float(result.get("score", 0.0) or 0.0),
        "success": state == "landed",
        "failure_mode": "none" if state == "landed" else state,
    }
    if "plot_path" in result:
        record["plot_path"] = result.get("plot_path")
    if "plot_paths" in result:
        record["plot_paths"] = result.get("plot_paths")
    return record


def aggregate_eval_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    landed = sum(1 for r in records if r.get("state") == "landed")
    crashes = sum(1 for r in records if r.get("state") == "crashed")
    out_of_fuel = sum(1 for r in records if r.get("state") == "out_of_fuel")
    flying = sum(1 for r in records if r.get("state") == "flying")
    other = total - landed - crashes - out_of_fuel - flying
    success_rate = (landed / total) if total > 0 else 0.0

    by_scenario: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("scenario") or "default")
        item = by_scenario.setdefault(
            key,
            {
                "runs": 0,
                "landed": 0,
                "crashed": 0,
                "out_of_fuel": 0,
                "flying": 0,
                "other": 0,
                "success_rate": 0.0,
            },
        )
        item["runs"] += 1
        state = record.get("state")
        if state in ("landed", "crashed", "out_of_fuel", "flying"):
            item[state] += 1
        else:
            item["other"] += 1

    for item in by_scenario.values():
        runs = int(item["runs"])
        item["success_rate"] = (item["landed"] / runs) if runs > 0 else 0.0

    return {
        "runs": total,
        "landed": landed,
        "crashed": crashes,
        "out_of_fuel": out_of_fuel,
        "flying": flying,
        "other": other,
        "success_rate": success_rate,
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

