from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable

from core.eval import (
    aggregate_eval_records,
    default_artifact_path,
    write_csv_records,
    write_json_report,
)
from levels import create_level, list_available_levels

from app.config import BenchSettings, RunSettings
from app.reporting import print_batch_summary
from app.run_single import (
    resolve_default_bot,
    run_once_record,
    set_eval_scenario,
)

_AUTO_RANDOMIZED_BATCH_SEEDS: tuple[int, ...] = tuple(range(10))


def parse_seed_spec(spec: str) -> list[int]:
    values: list[int] = []
    for token in (p.strip() for p in spec.split(",")):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if end >= start else -1
            values.extend(range(start, end + step, step))
        else:
            values.append(int(token))

    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_name_csv(spec: str) -> list[str]:
    out: list[str] = []
    for token in (p.strip() for p in spec.split(",")):
        if token:
            out.append(token)
    return out


def list_quick_benchmark_levels() -> list[str]:
    preferred = ["plunge", "flare", "coast", "setup"]
    available = set(list_available_levels())
    return [name for name in preferred if name in available]


def resolve_level_scenarios(level_name: str, *, quick: bool = False) -> list[str]:
    try:
        level = create_level(level_name)
    except Exception:
        return []
    if quick:
        list_scenarios = getattr(level, "list_quick_benchmark_scenarios", None)
        if not callable(list_scenarios):
            list_scenarios = getattr(level, "list_batch_scenarios", None)
    else:
        list_scenarios = getattr(level, "list_batch_scenarios", None)
    if not callable(list_scenarios):
        return []
    out = [str(name).strip() for name in list_scenarios()]
    return [name for name in out if name]


def resolve_scenarios_for_level(
    cfg: BenchSettings,
    level_name: str,
    *,
    resolver: Callable[[str, bool], list[str]] | None = None,
) -> list[str]:
    local_resolver = resolver or (lambda name, quick: resolve_level_scenarios(name, quick=quick))
    if cfg.scenarios_csv:
        return parse_name_csv(cfg.scenarios_csv)
    if cfg.scenario_name:
        return [cfg.scenario_name]
    if cfg.quick:
        return local_resolver(level_name, True)
    return local_resolver(level_name, False)


def resolve_benchmark_plan(cfg: BenchSettings) -> tuple[list[int], list[str]]:
    if cfg.quick:
        seeds = [0]
        levels = list_quick_benchmark_levels() or [cfg.level_name]
        return seeds, levels

    if cfg.seeds_csv:
        seeds = parse_seed_spec(cfg.seeds_csv)
    else:
        seeds = [0]

    if cfg.level_names_csv:
        levels = parse_name_csv(cfg.level_names_csv)
    else:
        levels = [cfg.level_name]
    return seeds, levels


def _scenario_has_randomized_fields(level_name: str, scenario_name: str | None) -> bool:
    try:
        level = create_level(level_name)
        set_eval_scenario(level, scenario_name)
        checker = getattr(level, "scenario_has_randomized_fields", None)
        if callable(checker):
            try:
                return bool(checker(scenario_name))
            except TypeError:
                return bool(checker())
    except Exception:
        return False
    return False


def _to_run_settings(cfg: BenchSettings) -> RunSettings:
    return RunSettings(
        level_name=cfg.level_name,
        bot_name=cfg.bot_name,
        seed=None,
        scenario_name=cfg.scenario_name,
        lander_name=cfg.lander_name,
        eval_mode=cfg.eval_mode,
        print_freq=0,
        max_time=cfg.max_time,
        max_steps=cfg.max_steps,
        plot_mode=cfg.plot_mode,
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        headless=True,
    )


def _run_batch_sequential(
    run_settings: RunSettings,
    run_plan: list[tuple[int, str, str | None]],
    *,
    benchmark_mode: str,
) -> list[dict[str, Any]]:
    total = len(run_plan)
    records: list[dict[str, Any]] = []
    for run_idx, (seed, level_name, scenario_name) in enumerate(run_plan, start=1):
        if scenario_name is not None:
            print(f"[{run_idx}/{total}] seed={seed} level={level_name} scenario={scenario_name}")
        else:
            print(f"[{run_idx}/{total}] seed={seed} level={level_name}")
        records.append(
            run_once_record(
                run_settings,
                seed=seed,
                level_name=level_name,
                eval_scenario_name=scenario_name,
                benchmark_mode=benchmark_mode,
            )
        )
    return records


def run_benchmark(cfg: BenchSettings) -> int:
    run_settings = _to_run_settings(cfg)

    seeds, levels = resolve_benchmark_plan(cfg)
    if not seeds:
        raise ValueError("Benchmark resolved no seeds")
    if not levels:
        raise ValueError("Benchmark resolved no levels")

    default_bot_cache: dict[str, str | None] = {}
    level_scenarios_cache: dict[tuple[str, bool], list[str]] = {}
    scenario_randomized_cache: dict[tuple[str, str | None], bool] = {}

    def resolve_default_bot_cached(level_name: str) -> str | None:
        if level_name not in default_bot_cache:
            default_bot_cache[level_name] = resolve_default_bot(level_name)
        return default_bot_cache[level_name]

    def resolve_level_scenarios_cached(level_name: str, quick: bool) -> list[str]:
        key = (level_name, quick)
        if key not in level_scenarios_cache:
            level_scenarios_cache[key] = resolve_level_scenarios(level_name, quick=quick)
        return level_scenarios_cache[key]

    def scenario_has_randomized_cached(level_name: str, scenario_name: str | None) -> bool:
        key = (level_name, scenario_name)
        if key not in scenario_randomized_cache:
            scenario_randomized_cache[key] = _scenario_has_randomized_fields(level_name, scenario_name)
        return scenario_randomized_cache[key]

    run_plan: list[tuple[int, str, str | None]] = []
    explicit_seed_control = bool(cfg.quick or cfg.seeds_csv is not None)

    for level_name in levels:
        scenarios = resolve_scenarios_for_level(
            cfg,
            level_name,
            resolver=resolve_level_scenarios_cached,
        )
        if not scenarios:
            if explicit_seed_control:
                scenario_seeds = seeds
            elif scenario_has_randomized_cached(level_name, None):
                scenario_seeds = list(_AUTO_RANDOMIZED_BATCH_SEEDS)
            else:
                scenario_seeds = [0]
            run_plan.extend((seed, level_name, None) for seed in scenario_seeds)
            continue

        for scenario_name in scenarios:
            if explicit_seed_control:
                scenario_seeds = seeds
            elif scenario_has_randomized_cached(level_name, scenario_name):
                scenario_seeds = list(_AUTO_RANDOMIZED_BATCH_SEEDS)
            else:
                scenario_seeds = [0]
            run_plan.extend((seed, level_name, scenario_name) for seed in scenario_seeds)

    total = len(run_plan)
    if total <= 0:
        raise ValueError("Benchmark resolved no runs")

    if cfg.bot_name is None:
        missing_defaults = [
            level_name for level_name in levels if resolve_default_bot_cached(level_name) is None
        ]
        if missing_defaults:
            missing_csv = ",".join(missing_defaults)
            raise ValueError(
                "Benchmark requires a bot name when levels have no default bot: "
                f"{missing_csv}"
            )

    worker_count = max(1, min(cfg.workers, total, os.cpu_count() or 1))
    print(f"Batch workers: requested={cfg.workers} effective={worker_count}")

    benchmark_mode = "median" if cfg.quick else "sample"
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
                for run_idx, (seed, level_name, scenario_name) in enumerate(run_plan, start=1):
                    fut = pool.submit(
                        run_once_record,
                        run_settings,
                        seed=seed,
                        level_name=level_name,
                        eval_scenario_name=scenario_name,
                        benchmark_mode=benchmark_mode,
                    )
                    future_map[fut] = (run_idx, seed, level_name, scenario_name)

                done = 0
                for fut in as_completed(future_map):
                    run_idx, seed, level_name, scenario_name = future_map[fut]
                    try:
                        record = fut.result()
                    except Exception as exc:
                        scenario_label = f" scenario={scenario_name}" if scenario_name is not None else ""
                        raise RuntimeError(
                            f"run {run_idx}/{total} seed={seed} level={level_name}"
                            f"{scenario_label} failed ({type(exc).__name__}: {exc})"
                        ) from exc

                    done += 1
                    if scenario_name is not None:
                        print(
                            f"[{done}/{total}] done seed={seed} level={level_name} "
                            f"scenario={scenario_name}"
                        )
                    else:
                        print(f"[{done}/{total}] done seed={seed} level={level_name}")
                    indexed_records[run_idx] = record

            records = [indexed_records[i] for i in range(1, total + 1)]
        except Exception as exc:
            print(
                f"Batch workers unavailable ({type(exc).__name__}: {exc}); "
                "falling back to sequential execution."
            )
            records = _run_batch_sequential(
                run_settings,
                run_plan,
                benchmark_mode=benchmark_mode,
            )

    summary = aggregate_eval_records(records)
    failed = [r for r in records if not r.get("success", False)]
    used_seeds = sorted({seed for seed, _level_name, _scenario_name in run_plan})

    batch_bot_name = cfg.bot_name or "level_default"

    json_path = None
    csv_path = None
    if cfg.json_path:
        json_target = (
            default_artifact_path(
                kind="json",
                level_name=cfg.level_name,
                bot_name=batch_bot_name,
                seeds=used_seeds,
                scenarios=levels,
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
                level_name=cfg.level_name,
                bot_name=batch_bot_name,
                seeds=used_seeds,
                scenarios=levels,
            )
            if cfg.csv_path == "auto"
            else cfg.csv_path
        )
        csv_path = write_csv_records(csv_target, records)

    print_batch_summary(summary, failed, json_path, csv_path)
    return 0 if summary["successes"] == summary["runs"] else 1
