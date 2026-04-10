from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from app.config import BenchSettings, BenchTarget, RunSettings
from app.reporting import print_batch_summary
from app.run_single import create_level_checked, resolve_default_bot, run_once_record
from app.selector import parse_seed_spec, render_selector_group
from game.core.eval import (
    aggregate_eval_records,
    collision_safe_path,
    default_artifact_path,
)
from game.core.level_capabilities import (
    scenario_has_randomized_fields_safe,
    set_eval_goal_checked,
    set_eval_scenario_checked,
)
from game.levels.registry import is_public_level
from bot_framework.scenarios import ScenarioBinding
from bot_framework.scenarios import expand_scenario_bindings as expand_selector_bindings
from utils.tracepack import TRACEPACK_SCHEMA, TRACEPACK_SCHEMA_VERSION

_AUTO_RANDOMIZED_BATCH_SEEDS: tuple[int, ...] = tuple(range(10))


def _expand_runtime_bindings(
    level_name: str,
    *,
    scenario_path: tuple[str, ...] | list[str] | None,
    allow_wildcards: bool,
) -> list[ScenarioBinding]:
    if is_public_level(level_name):
        if scenario_path:
            raise ValueError(
                f"Gameplay level '{level_name}' does not accept scenario selectors"
            )
        normalized = str(level_name).strip().lower()
        return [
            ScenarioBinding(
                level_name=normalized,
                path=(),
                runtime_level_name=normalized,
                runtime_scenario_name=None,
            )
        ]
    try:
        return expand_selector_bindings(
            level_name,
            scenario_path=scenario_path,
            allow_wildcards=allow_wildcards,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Unknown scenario root "):
            raise ValueError(f"Unknown level '{level_name}'") from exc
        raise


@dataclass(frozen=True)
class ResolvedBenchRun:
    seed: int
    level_name: str
    scenario_name: str | None
    runtime_level_name: str
    runtime_scenario_name: str | None
    eval_goal_name: str
    run_instance_id: int = 1
    run_key: str | None = None

    def display_label(self) -> str:
        goal_label = (
            "" if self.eval_goal_name == "landing" else f" goal={self.eval_goal_name}"
        )
        if self.scenario_name is not None:
            return (
                f"seed={self.seed} level={self.level_name} "
                f"scenario={self.scenario_name}{goal_label}"
            )
        return f"seed={self.seed} level={self.level_name}{goal_label}"


def _run_selector(target: ResolvedBenchRun) -> str:
    selector = render_selector_group(
        level_name=target.level_name,
        scenario_name=target.scenario_name,
        goal=target.eval_goal_name,
    )
    return f"{selector}:{int(target.seed)}"


def _assign_run_keys(run_plan: list[ResolvedBenchRun]) -> list[ResolvedBenchRun]:
    totals: dict[str, int] = {}
    for target in run_plan:
        selector = _run_selector(target)
        totals[selector] = totals.get(selector, 0) + 1
    seen: dict[str, int] = {}
    assigned: list[ResolvedBenchRun] = []
    for target in run_plan:
        selector = _run_selector(target)
        instance_id = seen.get(selector, 0) + 1
        seen[selector] = instance_id
        run_key = (
            selector if totals.get(selector, 0) <= 1 else f"{selector}#{instance_id}"
        )
        assigned.append(replace(target, run_instance_id=instance_id, run_key=run_key))
    return assigned


def _tracepack_root_for(path: Path) -> Path:
    return path.with_suffix("")


def _write_json_exact(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _resolve_output_path(
    path_value: str | None,
    *,
    kind: str,
    level_name: str,
    bot_name: str,
    seeds: list[int],
    scenarios: list[str],
) -> Path | None:
    if not path_value:
        return None
    if path_value == "auto":
        target = default_artifact_path(
            kind=kind,
            level_name=level_name,
            bot_name=bot_name,
            seeds=seeds,
            scenarios=scenarios,
        )
        return collision_safe_path(target).resolve()
    return Path(path_value).resolve()


def _scenario_has_randomized_fields(
    runtime_level_name: str, runtime_scenario_name: str | None
) -> bool:
    level = create_level_checked(runtime_level_name)
    set_eval_scenario_checked(level, runtime_scenario_name)
    return scenario_has_randomized_fields_safe(level, runtime_scenario_name)


def _resolve_goal(runtime_level_name: str, eval_goal: str) -> str:
    level = create_level_checked(runtime_level_name)
    return set_eval_goal_checked(level, eval_goal)


def resolve_selector_plan(
    target: BenchTarget,
    *,
    randomized_checker: Callable[[str, str | None], bool] | None = None,
    goal_resolver: Callable[[str, str], str] | None = None,
) -> list[ResolvedBenchRun]:
    checker = randomized_checker or _scenario_has_randomized_fields
    resolve_goal = goal_resolver or _resolve_goal
    explicit_seeds = parse_seed_spec(target.seed_spec) if target.seed_spec else None

    if explicit_seeds is not None and not explicit_seeds:
        raise ValueError(
            f"Selector '{target.level_name}' resolved an empty seed list from '{target.seed_spec}'"
        )

    bindings = _expand_runtime_bindings(
        target.level_name,
        scenario_path=target.scenario_path,
        allow_wildcards=True,
    )

    run_plan: list[ResolvedBenchRun] = []
    for binding in bindings:
        resolved_goal = resolve_goal(binding.runtime_level_name, target.eval_goal)
        if explicit_seeds is not None:
            seeds = explicit_seeds
        elif checker(binding.runtime_level_name, binding.runtime_scenario_name):
            seeds = list(_AUTO_RANDOMIZED_BATCH_SEEDS)
        else:
            seeds = [0]
        run_plan.extend(
            ResolvedBenchRun(
                seed,
                binding.level_name,
                binding.scenario_name,
                binding.runtime_level_name,
                binding.runtime_scenario_name,
                resolved_goal,
            )
            for seed in seeds
        )
    return run_plan


def resolve_benchmark_plan(cfg: BenchSettings) -> list[ResolvedBenchRun]:
    if not cfg.selectors:
        raise ValueError("Benchmark requires at least one selector")

    scenario_randomized_cache: dict[tuple[str, str | None], bool] = {}
    goal_cache: dict[tuple[str, str], str] = {}

    def scenario_has_randomized_cached(
        runtime_level_name: str, runtime_scenario_name: str | None
    ) -> bool:
        key = (runtime_level_name, runtime_scenario_name)
        if key not in scenario_randomized_cache:
            scenario_randomized_cache[key] = _scenario_has_randomized_fields(
                runtime_level_name,
                runtime_scenario_name,
            )
        return scenario_randomized_cache[key]

    def resolve_goal_cached(runtime_level_name: str, eval_goal: str) -> str:
        key = (runtime_level_name, eval_goal)
        if key not in goal_cache:
            goal_cache[key] = _resolve_goal(runtime_level_name, eval_goal)
        return goal_cache[key]

    run_plan: list[ResolvedBenchRun] = []
    for target in cfg.selectors:
        run_plan.extend(
            resolve_selector_plan(
                target,
                randomized_checker=scenario_has_randomized_cached,
                goal_resolver=resolve_goal_cached,
            )
        )
    return _assign_run_keys(run_plan)


def _to_run_settings(
    cfg: BenchSettings, *, trace_root_dir: Path | None = None
) -> RunSettings:
    first_binding = _expand_runtime_bindings(
        cfg.selectors[0].level_name,
        scenario_path=cfg.selectors[0].scenario_path,
        allow_wildcards=True,
    )[0]
    return RunSettings(
        level_name=first_binding.level_name,
        runtime_level_name=first_binding.runtime_level_name,
        bot_name=cfg.bot_name,
        bot_config_path=cfg.bot_config_path,
        seed=None,
        scenario_name=first_binding.scenario_name,
        runtime_scenario_name=first_binding.runtime_scenario_name,
        eval_goal=cfg.selectors[0].eval_goal,
        lander_name=cfg.lander_name,
        print_freq=0,
        max_time=cfg.max_time,
        max_steps=cfg.max_steps,
        trace_enabled=cfg.trace_enabled,
        trace_sample_period_s=cfg.trace_sample_period_s,
        trace_detail=cfg.trace_detail,
        trace_root_dir=(str(trace_root_dir) if trace_root_dir is not None else None),
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        headless=True,
        bot_profile_enabled=cfg.bot_profile_enabled,
        bot_profile_interval_s=cfg.bot_profile_interval_s,
        bot_profile_log_lines=cfg.bot_profile_log_lines,
    )


def _run_batch_sequential(
    run_settings: RunSettings,
    run_plan: list[ResolvedBenchRun],
    *,
    benchmark_mode: str,
) -> list[dict[str, Any]]:
    total = len(run_plan)
    records: list[dict[str, Any]] = []
    for run_idx, target in enumerate(run_plan, start=1):
        print(f"[{run_idx}/{total}] {target.display_label()}")
        records.append(
            run_once_record(
                run_settings,
                seed=target.seed,
                level_name=target.runtime_level_name,
                eval_scenario_name=target.runtime_scenario_name,
                eval_goal_name=target.eval_goal_name,
                record_level_name=target.level_name,
                record_scenario_name=target.scenario_name,
                benchmark_mode=benchmark_mode,
                trace_selector_tag=target.run_key,
                run_key=target.run_key,
                run_instance_id=target.run_instance_id,
            )
        )
    return records


def run_benchmark(cfg: BenchSettings) -> int:
    run_plan = resolve_benchmark_plan(cfg)
    total = len(run_plan)
    if total <= 0:
        raise ValueError("Benchmark resolved no runs")

    unique_levels = sorted({target.level_name for target in run_plan})
    if cfg.bot_name is None:
        missing_defaults = [
            level_name
            for level_name in unique_levels
            if resolve_default_bot(level_name) is None
        ]
        if missing_defaults:
            missing_csv = ",".join(missing_defaults)
            raise ValueError(
                "Benchmark requires a bot name when levels have no default bot: "
                f"{missing_csv}"
            )

    artifact_level = unique_levels[0] if len(unique_levels) == 1 else "batch"
    artifact_tags = sorted(
        {
            render_selector_group(
                level_name=target.level_name,
                scenario_name=target.scenario_name,
                goal=target.eval_goal_name,
            )
            for target in run_plan
        }
    )
    used_seeds = sorted({target.seed for target in run_plan})
    batch_bot_name = cfg.bot_name or "level_default"

    tracepack_path: Path | None = None
    trace_root_dir: Path | None = None
    tracepack_path = _resolve_output_path(
        cfg.json_path,
        kind="tracepack.json",
        level_name=artifact_level,
        bot_name=batch_bot_name,
        seeds=used_seeds,
        scenarios=artifact_tags,
    )
    if tracepack_path is not None:
        trace_root_dir = _tracepack_root_for(tracepack_path)

    run_settings = _to_run_settings(cfg, trace_root_dir=trace_root_dir)
    worker_count = max(1, min(cfg.workers, total, os.cpu_count() or 1))
    print(f"Batch workers: requested={cfg.workers} effective={worker_count}")

    benchmark_mode = "sample"
    benchmark_started = perf_counter()
    if worker_count <= 1:
        records = _run_batch_sequential(
            run_settings,
            run_plan,
            benchmark_mode=benchmark_mode,
        )
    else:
        indexed_records: dict[int, dict[str, Any]] = {}
        try:
            with ProcessPoolExecutor(max_workers=worker_count) as pool:
                future_map = {}
                for run_idx, target in enumerate(run_plan, start=1):
                    fut = pool.submit(
                        run_once_record,
                        run_settings,
                        seed=target.seed,
                        level_name=target.runtime_level_name,
                        eval_scenario_name=target.runtime_scenario_name,
                        eval_goal_name=target.eval_goal_name,
                        record_level_name=target.level_name,
                        record_scenario_name=target.scenario_name,
                        benchmark_mode=benchmark_mode,
                        trace_selector_tag=target.run_key,
                        run_key=target.run_key,
                        run_instance_id=target.run_instance_id,
                    )
                    future_map[fut] = (run_idx, target)

                done = 0
                for fut in as_completed(future_map):
                    run_idx, target = future_map[fut]
                    try:
                        record = fut.result()
                    except Exception as exc:
                        raise RuntimeError(
                            f"run {run_idx}/{total} {target.display_label()} "
                            f"failed ({type(exc).__name__}: {exc})"
                        ) from exc

                    done += 1
                    print(f"[{done}/{total}] done {target.display_label()}")
                    indexed_records[run_idx] = record

            records = [indexed_records[i] for i in range(1, total + 1)]
        except RuntimeError:
            raise
        except Exception as exc:
            raise ValueError(
                "Batch workers unavailable; refusing implicit sequential fallback. "
                f"Cause: {type(exc).__name__}: {exc}. "
                "Resolve worker/process support and rerun."
            ) from exc

    benchmark_wall_clock_s = perf_counter() - benchmark_started
    summary = aggregate_eval_records(records)
    failed = [r for r in records if not r.get("success", False)]
    trace_index = [
        {
            "selector": render_selector_group(
                level_name=str(record.get("level") or ""),
                scenario_name=str(record.get("scenario") or ""),
                goal=str(record.get("eval_goal") or "landing"),
            )
            + f":{int(record.get('seed', 0) or 0)}",
            "run_key": record.get("run_key"),
            "run_instance_id": record.get("run_instance_id"),
            "trace_path": record.get("trace_path"),
            "trace_rel_path": record.get("trace_rel_path"),
            "trace_preview_path": record.get("trace_preview_path"),
            "trace_preview_rel_path": record.get("trace_preview_rel_path"),
        }
        for record in records
    ]

    if tracepack_path is not None:
        outputs_root = Path("outputs").resolve()
        tracepack_payload = {
            "schema": TRACEPACK_SCHEMA,
            "schema_version": TRACEPACK_SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "benchmark_wall_clock_s": benchmark_wall_clock_s,
            "trace_enabled": bool(cfg.trace_enabled),
            "trace_sample_period_s": float(cfg.trace_sample_period_s),
            "trace_detail": str(cfg.trace_detail),
            "trace_root_path": (
                str(trace_root_dir) if trace_root_dir is not None else None
            ),
            "trace_root_rel": (
                trace_root_dir.relative_to(outputs_root).as_posix()
                if trace_root_dir is not None
                and trace_root_dir.is_relative_to(outputs_root)
                else None
            ),
            "run_index": trace_index,
            "summary": summary,
            "records": records,
        }
        _write_json_exact(tracepack_path, tracepack_payload)

    print_batch_summary(summary, failed, tracepack_path)
    return 0 if summary["successes"] == summary["runs"] else 1
