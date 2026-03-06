from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from core.eval import (
    aggregate_eval_records,
    default_artifact_path,
    write_csv_records,
    write_json_report,
)
from core.level_capabilities import (
    list_batch_scenarios_safe,
    scenario_has_randomized_fields_safe,
    set_eval_goal_checked,
    set_eval_scenario_checked,
)
from levels import create_level

from app.config import BenchSettings, BenchTarget, RunSettings
from app.reporting import print_batch_summary
from app.run_single import (
    resolve_default_bot,
    run_once_record,
)
from app.selector import parse_seed_spec, render_selector_group

_AUTO_RANDOMIZED_BATCH_SEEDS: tuple[int, ...] = tuple(range(10))


@dataclass(frozen=True)
class ResolvedBenchRun:
    seed: int
    level_name: str
    scenario_name: str | None
    eval_goal_name: str

    def display_label(self) -> str:
        goal_label = "" if self.eval_goal_name == "landing" else f" goal={self.eval_goal_name}"
        if self.scenario_name is not None:
            return (
                f"seed={self.seed} level={self.level_name} "
                f"scenario={self.scenario_name}{goal_label}"
            )
        return f"seed={self.seed} level={self.level_name}{goal_label}"


def resolve_level_scenarios(level_name: str) -> list[str]:
    try:
        level = create_level(level_name)
    except Exception:
        return []
    return list_batch_scenarios_safe(level)


def _scenario_has_randomized_fields(level_name: str, scenario_name: str | None) -> bool:
    try:
        level = create_level(level_name)
        set_eval_scenario_checked(level, scenario_name)
        return scenario_has_randomized_fields_safe(level, scenario_name)
    except Exception:
        return False


def resolve_selector_plan(
    target: BenchTarget,
    *,
    scenario_resolver: Callable[[str], list[str]] | None = None,
    randomized_checker: Callable[[str, str | None], bool] | None = None,
) -> list[ResolvedBenchRun]:
    resolver = scenario_resolver or resolve_level_scenarios
    checker = randomized_checker or _scenario_has_randomized_fields
    explicit_seeds = parse_seed_spec(target.seed_spec) if target.seed_spec else None

    if explicit_seeds is not None and not explicit_seeds:
        raise ValueError(
            f"Selector '{target.level_name}' resolved an empty seed list from '{target.seed_spec}'"
        )

    scenarios: list[str | None]
    if target.scenario_name is not None:
        scenarios = [target.scenario_name]
    else:
        listed = resolver(target.level_name)
        scenarios = listed if listed else [None]

    level = create_level(target.level_name)
    resolved_goal = set_eval_goal_checked(level, target.eval_goal)

    run_plan: list[ResolvedBenchRun] = []
    for scenario_name in scenarios:
        if explicit_seeds is not None:
            seeds = explicit_seeds
        elif checker(target.level_name, scenario_name):
            seeds = list(_AUTO_RANDOMIZED_BATCH_SEEDS)
        else:
            seeds = [0]
        run_plan.extend(
            ResolvedBenchRun(seed, target.level_name, scenario_name, resolved_goal)
            for seed in seeds
        )
    return run_plan


def resolve_benchmark_plan(cfg: BenchSettings) -> list[ResolvedBenchRun]:
    if not cfg.selectors:
        raise ValueError("Benchmark requires at least one selector")

    level_scenarios_cache: dict[str, list[str]] = {}
    scenario_randomized_cache: dict[tuple[str, str | None], bool] = {}

    def resolve_level_scenarios_cached(level_name: str) -> list[str]:
        if level_name not in level_scenarios_cache:
            level_scenarios_cache[level_name] = resolve_level_scenarios(level_name)
        return level_scenarios_cache[level_name]

    def scenario_has_randomized_cached(level_name: str, scenario_name: str | None) -> bool:
        key = (level_name, scenario_name)
        if key not in scenario_randomized_cache:
            scenario_randomized_cache[key] = _scenario_has_randomized_fields(level_name, scenario_name)
        return scenario_randomized_cache[key]

    run_plan: list[ResolvedBenchRun] = []
    for target in cfg.selectors:
        run_plan.extend(
            resolve_selector_plan(
                target,
                scenario_resolver=resolve_level_scenarios_cached,
                randomized_checker=scenario_has_randomized_cached,
            )
        )
    return run_plan


def _to_run_settings(cfg: BenchSettings) -> RunSettings:
    first_level = cfg.selectors[0].level_name
    return RunSettings(
        level_name=first_level,
        bot_name=cfg.bot_name,
        bot_config_path=cfg.bot_config_path,
        seed=None,
        scenario_name=None,
        eval_goal=cfg.selectors[0].eval_goal,
        lander_name=cfg.lander_name,
        print_freq=0,
        max_time=cfg.max_time,
        max_steps=cfg.max_steps,
        plot_mode=cfg.plot_mode,
        plot_output=cfg.plot_output,
        plot_max_side_px=cfg.plot_max_side_px,
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
                level_name=target.level_name,
                eval_scenario_name=target.scenario_name,
                eval_goal_name=target.eval_goal_name,
                benchmark_mode=benchmark_mode,
            )
        )
    return records


def run_benchmark(cfg: BenchSettings) -> int:
    run_settings = _to_run_settings(cfg)
    run_plan = resolve_benchmark_plan(cfg)
    total = len(run_plan)
    if total <= 0:
        raise ValueError("Benchmark resolved no runs")

    unique_levels = sorted({target.level_name for target in run_plan})
    if cfg.bot_name is None:
        missing_defaults = [
            level_name for level_name in unique_levels if resolve_default_bot(level_name) is None
        ]
        if missing_defaults:
            missing_csv = ",".join(missing_defaults)
            raise ValueError(
                "Benchmark requires a bot name when levels have no default bot: "
                f"{missing_csv}"
            )

    worker_count = max(1, min(cfg.workers, total, os.cpu_count() or 1))
    print(f"Batch workers: requested={cfg.workers} effective={worker_count}")

    benchmark_mode = "sample"
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
                        level_name=target.level_name,
                        eval_scenario_name=target.scenario_name,
                        eval_goal_name=target.eval_goal_name,
                        benchmark_mode=benchmark_mode,
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

    summary = aggregate_eval_records(records)
    failed = [r for r in records if not r.get("success", False)]
    used_seeds = sorted({target.seed for target in run_plan})

    batch_bot_name = cfg.bot_name or "level_default"
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

    json_path = None
    csv_path = None
    if cfg.json_path:
        json_target = (
            default_artifact_path(
                kind="json",
                level_name=artifact_level,
                bot_name=batch_bot_name,
                seeds=used_seeds,
                scenarios=artifact_tags,
            )
            if cfg.json_path == "auto"
            else cfg.json_path
        )
        json_path = write_json_report(
            json_target,
            {
                "summary": summary,
                "records": records,
            },
        )

    if cfg.csv_path:
        csv_target = (
            default_artifact_path(
                kind="csv",
                level_name=artifact_level,
                bot_name=batch_bot_name,
                seeds=used_seeds,
                scenarios=artifact_tags,
            )
            if cfg.csv_path == "auto"
            else cfg.csv_path
        )
        csv_path = write_csv_records(csv_target, records)

    print_batch_summary(summary, failed, json_path, csv_path)
    return 0 if summary["successes"] == summary["runs"] else 1
