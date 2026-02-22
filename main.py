"""Main entry point for lunar lander game (thin wrapper)."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from core.eval import (
    aggregate_eval_records,
    default_artifact_path,
    normalize_run_result,
    write_csv_records,
    write_json_report,
)
from game import LanderGame
from bots import create_bot, list_available_bots
from levels import create_level, list_available_levels
from landers import list_available_landers


@dataclass
class RunConfig:
    level_name: str
    bot_name: str | None
    headless: bool
    batch: bool
    print_freq: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    stop_on_crash: bool
    stop_on_out_of_fuel: bool
    stop_on_first_land: bool
    seed: int | None
    lander_name: str | None
    eval_scenario: str | None
    batch_seeds: str | None
    batch_scenarios: str | None
    batch_json: str | None
    batch_csv: str | None
    quick_benchmark: bool
    batch_workers: int


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}:\n  (none)"
    joined = "\n  ".join(items)
    return f"{title}:\n  {joined}"


def _build_parser() -> argparse.ArgumentParser:
    levels = list_available_levels()
    bots = list_available_bots()
    landers = list_available_landers()

    epilog = "\n".join(
        [
            _format_list("Available levels", levels),
            _format_list("Available bots", bots),
            _format_list("Available landers", landers),
        ]
    )

    parser = argparse.ArgumentParser(
        description="Lunar Lander Game",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument("level_name", choices=levels, help="Level module name")
    parser.add_argument("bot_name", nargs="?", choices=bots, help="Bot name")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without graphics (requires bot)",
    )
    parser.add_argument(
        "--freq",
        type=int,
        default=None,
        help="Print stats every N frames (60=1/sec, 1=every frame, 0=off)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Limit simulation to N steps (headless mode)",
    )
    parser.add_argument(
        "--time",
        type=float,
        default=None,
        help="Headless: limit simulation to S seconds (default: 300)",
    )
    parser.add_argument(
        "--plot",
        choices=("none", "speed", "thrust", "all"),
        default=None,
        help="Headless: trajectory plot mode",
    )
    parser.add_argument(
        "--stop-on-crash",
        action="store_true",
        help="Terminate when the lander crashes",
    )
    parser.add_argument(
        "--stop-on-out-of-fuel",
        action="store_true",
        help="Terminate when fuel is depleted",
    )
    parser.add_argument(
        "--stop-on-first-land",
        action="store_true",
        help="Terminate after first landing",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--lander", choices=landers, help="Choose lander variant")
    parser.add_argument(
        "--eval-scenario",
        type=str,
        default=None,
        help="Eval scenario name (used by level_eval)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run a multi-seed/multi-scenario batch",
    )
    parser.add_argument(
        "--batch-seeds",
        type=str,
        default=None,
        help="Batch seed spec, e.g. 0-19 or 0,1,2,5",
    )
    parser.add_argument(
        "--batch-scenarios",
        type=str,
        default=None,
        help="Comma-separated scenario list for level_eval batch runs",
    )
    parser.add_argument(
        "--batch-json",
        type=str,
        default=None,
        help="Write batch report JSON to path (or 'auto')",
    )
    parser.add_argument(
        "--batch-csv",
        type=str,
        default=None,
        help="Write batch rows CSV to path (or 'auto')",
    )
    parser.add_argument(
        "--quick-benchmark",
        action="store_true",
        help="Run a small fixed benchmark preset for fast iteration",
    )
    parser.add_argument(
        "--batch-workers",
        type=int,
        default=1,
        help="Batch worker processes (1 = sequential)",
    )
    return parser


def _parse_args(args: argparse.Namespace) -> RunConfig:
    batch_mode = bool(
        args.batch
        or args.quick_benchmark
        or args.batch_seeds is not None
        or args.batch_scenarios is not None
        or args.batch_json is not None
        or args.batch_csv is not None
    )
    print_freq = (0 if batch_mode else 60) if args.freq is None else args.freq
    max_time = 300.0 if args.time is None else args.time
    plot_mode = "none" if args.plot is None else args.plot

    return RunConfig(
        level_name=args.level_name,
        bot_name=args.bot_name,
        headless=args.headless,
        batch=args.batch,
        print_freq=print_freq,
        max_time=max_time,
        max_steps=args.steps,
        plot_mode=plot_mode,
        stop_on_crash=args.stop_on_crash,
        stop_on_out_of_fuel=args.stop_on_out_of_fuel,
        stop_on_first_land=args.stop_on_first_land,
        seed=args.seed,
        lander_name=args.lander,
        eval_scenario=args.eval_scenario,
        batch_seeds=args.batch_seeds,
        batch_scenarios=args.batch_scenarios,
        batch_json=args.batch_json,
        batch_csv=args.batch_csv,
        quick_benchmark=args.quick_benchmark,
        batch_workers=max(1, int(args.batch_workers)),
    )


def _announce_config(config: RunConfig, args: argparse.Namespace) -> None:
    if config.headless:
        print("Running in headless mode")

    if args.freq is not None:
        if config.print_freq == 0:
            print("Stats output disabled")
        elif config.print_freq == 1:
            print("Printing stats every frame")
        else:
            print(
                f"Printing stats every {config.print_freq} frames ({config.print_freq / 60:.2f}s)"
            )
    elif _is_batch_mode(config):
        print("Stats output disabled (batch default)")

    if args.time is not None:
        print(f"Max time: {config.max_time}s (headless mode)")

    if args.plot is not None:
        print(f"Plot mode: {config.plot_mode}")

    if config.stop_on_crash:
        print("Stop on crash: enabled")
    if config.stop_on_out_of_fuel:
        print("Stop on out-of-fuel: enabled")
    if config.stop_on_first_land:
        print("Stop on first land: enabled")

    if config.seed is not None:
        print(f"Using seed: {config.seed}")

    if config.lander_name:
        print(f"Using lander: {config.lander_name}")
    if config.eval_scenario:
        print(f"Eval scenario: {config.eval_scenario}")
    if _is_batch_mode(config):
        print("Batch mode: enabled")
        print(f"Batch workers: {config.batch_workers}")
        if config.batch_seeds:
            print(f"Batch seeds: {config.batch_seeds}")
        if config.batch_scenarios:
            print(f"Batch scenarios: {config.batch_scenarios}")
        if config.quick_benchmark:
            print("Quick benchmark preset: enabled")


def _print_headless_results(result: dict) -> None:
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    for key in (
        "time",
        "state",
        "landing_count",
        "crash_count",
        "credits",
        "fuel",
        "score",
    ):
        if key in result:
            val = result[key]
            if isinstance(val, float):
                print(f"{key.capitalize():<18}{val:.2f}")
            else:
                print(f"{key.capitalize():<18}{val}")
    print("=" * 60)
    if result.get("plot_paths"):
        print("Plots:")
        for p in result["plot_paths"]:
            print(f"  {p}")
    elif result.get("plot_path"):
        print(f"Plot:              {result['plot_path']}")
    if result.get("plot_error"):
        print(f"Plot error:        {result['plot_error']}")


def _is_batch_mode(config: RunConfig) -> bool:
    return bool(
        config.batch
        or config.quick_benchmark
        or config.batch_seeds is not None
        or config.batch_scenarios is not None
        or config.batch_json is not None
        or config.batch_csv is not None
    )


def _parse_seed_spec(spec: str) -> list[int]:
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
    # preserve insertion order while deduplicating
    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _parse_name_csv(spec: str) -> list[str]:
    out: list[str] = []
    for token in (p.strip() for p in spec.split(",")):
        if token:
            out.append(token)
    return out


def _list_eval_scenarios() -> list[str]:
    try:
        from levels.level_eval import list_eval_scenarios

        return list_eval_scenarios()
    except Exception:
        return []


def _resolve_batch_plan(config: RunConfig) -> tuple[list[int], list[str | None]]:
    eval_scenarios = _list_eval_scenarios()

    if config.quick_benchmark:
        seeds = [0, 1, 2]
        scenarios = [
            "spawn_above_target",
            "increase_horizontal_distance",
            "climb_to_target",
            "complex_terrain_vertical_features",
        ]
        if config.level_name != "level_eval":
            scenarios = [None]
        return seeds, scenarios

    seeds: list[int]
    if config.batch_seeds:
        seeds = _parse_seed_spec(config.batch_seeds)
    elif config.seed is not None:
        seeds = [config.seed]
    else:
        seeds = [0]

    scenarios: list[str | None]
    if config.level_name != "level_eval":
        scenarios = [None]
    elif config.batch_scenarios:
        scenarios = _parse_name_csv(config.batch_scenarios)
    elif config.eval_scenario:
        scenarios = [config.eval_scenario]
    elif eval_scenarios:
        scenarios = [eval_scenarios[0]]
    else:
        scenarios = [None]

    return seeds, scenarios


def _configure_level(level, config: RunConfig, scenario: str | None) -> None:
    stop_on_crash = config.stop_on_crash
    stop_on_out_of_fuel = config.stop_on_out_of_fuel
    stop_on_first_land = config.stop_on_first_land
    if config.headless:
        stop_on_crash = True
        stop_on_out_of_fuel = True
        stop_on_first_land = True
    level.stop_on_crash = stop_on_crash
    level.stop_on_out_of_fuel = stop_on_out_of_fuel
    level.stop_on_first_land = stop_on_first_land
    level.plot_mode = config.plot_mode
    level.max_time = config.max_time
    if config.lander_name:
        setattr(level, "lander_name", config.lander_name)
    if scenario is not None:
        setattr(level, "eval_scenario", scenario)


def _run_once(
    config: RunConfig,
    *,
    seed: int | None = None,
    scenario: str | None = None,
    print_results: bool = True,
) -> dict[str, Any]:
    level = create_level(config.level_name)
    _configure_level(level, config, scenario)
    bot = create_bot(config.bot_name) if config.bot_name is not None else None
    game = LanderGame(seed=seed, bot=bot, headless=config.headless, level=level)
    result = game.run(
        print_freq=config.print_freq,
        max_time=config.max_time,
        max_steps=config.max_steps,
    )
    if config.headless and print_results:
        _print_headless_results(result)
    return result


def _run_once_record(
    config: RunConfig,
    *,
    seed: int | None,
    scenario: str | None,
) -> dict[str, Any]:
    result = _run_once(
        config,
        seed=seed,
        scenario=scenario,
        print_results=False,
    )
    return normalize_run_result(
        bot_name=str(config.bot_name),
        level_name=config.level_name,
        scenario=scenario,
        seed=seed,
        result=result,
    )


def _print_batch_summary(
    summary: dict[str, Any],
    failures: list[dict[str, Any]],
    json_path,
    csv_path,
) -> None:
    print("\n" + "=" * 60)
    print("BATCH RESULTS")
    print("=" * 60)
    print(f"Runs:              {summary['runs']}")
    print(f"Landed:            {summary['landed']}")
    print(f"Crashed:           {summary['crashed']}")
    print(f"Out_of_fuel:       {summary['out_of_fuel']}")
    print(f"Flying:            {summary['flying']}")
    print(f"Other:             {summary['other']}")
    print(f"Success rate:      {summary['success_rate']:.2%}")
    if summary.get("by_scenario"):
        print("\nPer-scenario:")
        for name in sorted(summary["by_scenario"]):
            row = summary["by_scenario"][name]
            print(
                f"  - {name}: runs={row['runs']} landed={row['landed']} "
                f"crashed={row['crashed']} success={row['success_rate']:.2%}"
            )
    if failures:
        print("\nFail samples:")
        for row in failures[:8]:
            print(
                f"  - seed={row.get('seed')} scenario={row.get('scenario') or 'default'} "
                f"state={row.get('state')}"
            )
    if json_path is not None:
        print(f"\nJSON report:       {json_path}")
    if csv_path is not None:
        print(f"CSV report:        {csv_path}")
    print("=" * 60)


def _run_batch(config: RunConfig) -> int:
    if config.bot_name is None:
        raise ValueError("Batch mode requires a bot name")
    if not config.headless:
        raise ValueError("Batch mode requires --headless")

    seeds, scenarios = _resolve_batch_plan(config)
    run_plan = [(seed, scenario) for scenario in scenarios for seed in seeds]
    total = len(run_plan)
    records: list[dict[str, Any]] = []
    worker_count = max(1, min(config.batch_workers, total, os.cpu_count() or 1))

    if worker_count <= 1:
        for run_idx, (seed, scenario) in enumerate(run_plan, start=1):
            scenario_name = scenario or "default"
            print(f"[{run_idx}/{total}] seed={seed} scenario={scenario_name}")
            records.append(_run_once_record(config, seed=seed, scenario=scenario))
    else:
        indexed_records: dict[int, dict[str, Any]] = {}
        try:
            with ProcessPoolExecutor(max_workers=worker_count) as pool:
                future_map = {}
                for run_idx, (seed, scenario) in enumerate(run_plan, start=1):
                    fut = pool.submit(_run_once_record, config, seed=seed, scenario=scenario)
                    future_map[fut] = (run_idx, seed, scenario)
                done = 0
                for fut in as_completed(future_map):
                    run_idx, seed, scenario = future_map[fut]
                    scenario_name = scenario or "default"
                    done += 1
                    print(f"[{done}/{total}] done seed={seed} scenario={scenario_name}")
                    indexed_records[run_idx] = fut.result()
            records = [indexed_records[i] for i in range(1, total + 1)]
        except (PermissionError, OSError) as exc:
            print(
                f"Batch workers unavailable ({exc}); falling back to sequential execution."
            )
            for run_idx, (seed, scenario) in enumerate(run_plan, start=1):
                scenario_name = scenario or "default"
                print(f"[{run_idx}/{total}] seed={seed} scenario={scenario_name}")
                records.append(_run_once_record(config, seed=seed, scenario=scenario))

    summary = aggregate_eval_records(records)
    failed = [r for r in records if not r.get("success", False)]

    scenarios_non_null = [s for s in scenarios if s is not None]
    json_path = None
    csv_path = None
    if config.batch_json:
        json_target = (
            default_artifact_path(
                kind="json",
                level_name=config.level_name,
                bot_name=config.bot_name,
                seeds=seeds,
                scenarios=scenarios_non_null,
            )
            if config.batch_json == "auto"
            else config.batch_json
        )
        json_path = write_json_report(
            json_target,
            {
                "summary": summary,
                "records": records,
            },
        )
    if config.batch_csv:
        csv_target = (
            default_artifact_path(
                kind="csv",
                level_name=config.level_name,
                bot_name=config.bot_name,
                seeds=seeds,
                scenarios=scenarios_non_null,
            )
            if config.batch_csv == "auto"
            else config.batch_csv
        )
        csv_path = write_csv_records(csv_target, records)

    _print_batch_summary(summary, failed, json_path, csv_path)
    return 0 if summary["landed"] == summary["runs"] else 1


def main() -> None:
    """Entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    config = _parse_args(args)

    _announce_config(config, args)

    if config.headless and not config.bot_name:
        parser.error("Headless mode requires a bot name")
    if _is_batch_mode(config):
        try:
            exit_code = _run_batch(config)
            raise SystemExit(exit_code)
        except ValueError as exc:
            parser.error(str(exc))

    print(f"Using level {config.level_name}")
    if config.bot_name is not None:
        print(f"Running with bot {config.bot_name}")

    result = _run_once(
        config,
        seed=config.seed,
        scenario=config.eval_scenario,
        print_results=config.headless,
    )
    _ = result


if __name__ == "__main__":
    main()
