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
from bots.descent import list_behavior_names as list_descent_behaviors
from levels import create_level, list_available_levels
from landers import list_available_landers


@dataclass
class RunConfig:
    level_name: str
    bot_name: str | None
    bot_behavior: str | None
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
    batch_seeds: str | None
    batch_levels: str | None
    batch_json: str | None
    batch_csv: str | None
    quick_benchmark: bool
    batch_workers: int
    scenario_name: str | None = None
    batch_scenarios: str | None = None


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}:\n  (none)"
    joined = "\n  ".join(items)
    return f"{title}:\n  {joined}"


def _build_parser() -> argparse.ArgumentParser:
    levels = list_available_levels()
    bots = list_available_bots()
    descent_behaviors = list_descent_behaviors()
    landers = list_available_landers()
    default_level = "flat" if "flat" in levels else (levels[0] if levels else None)

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
    parser.add_argument(
        "level_name",
        nargs="?",
        default=default_level,
        choices=levels,
        help=f"Level module name (default: {default_level})",
    )
    parser.add_argument(
        "--bot",
        dest="bot",
        choices=bots,
        default=None,
        help="Bot name (overrides level default bot)",
    )
    parser.add_argument(
        "--bot-behavior",
        choices=descent_behaviors,
        default=None,
        help=(
            "Behavior profile for the descent bot "
            f"(choices: {', '.join(descent_behaviors)})"
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without graphics (requires bot or level default bot)",
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
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Run a specific scenario for levels that support scenario selection",
    )
    parser.add_argument("--lander", choices=landers, help="Choose lander variant")
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
        "--batch-levels",
        type=str,
        default=None,
        help="Comma-separated level list for batch runs",
    )
    parser.add_argument(
        "--batch-scenarios",
        type=str,
        default=None,
        help="Comma-separated scenario list for batch runs",
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
        or args.batch_levels is not None
        or args.batch_scenarios is not None
        or args.batch_json is not None
        or args.batch_csv is not None
    )
    print_freq = (0 if batch_mode else 60) if args.freq is None else args.freq
    max_time = 300.0 if args.time is None else args.time
    plot_mode = "none" if args.plot is None else args.plot

    return RunConfig(
        level_name=args.level_name,
        bot_name=args.bot,
        bot_behavior=(args.bot_behavior.strip() if args.bot_behavior else None),
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
        scenario_name=(args.scenario.strip() if args.scenario else None),
        lander_name=args.lander,
        batch_seeds=args.batch_seeds,
        batch_levels=args.batch_levels,
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
    if config.scenario_name:
        print(f"Using scenario: {config.scenario_name}")

    if config.lander_name:
        print(f"Using lander: {config.lander_name}")
    if _is_batch_mode(config):
        print("Batch mode: enabled")
        print(f"Batch workers requested: {config.batch_workers}")
        if config.batch_seeds:
            print(f"Batch seeds: {config.batch_seeds}")
        if config.batch_levels:
            print(f"Batch levels: {config.batch_levels}")
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
        "distance_flown",
        "landing_offset",
        "avg_speed",
        "fuel_consumed",
        "fuel_per_distance",
        "spawn_to_target_distance",
        "path_efficiency",
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
        or config.batch_levels is not None
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


def _list_wave1_levels() -> list[str]:
    preferred = ["drop"]
    available = set(list_available_levels())
    return [name for name in preferred if name in available]


def _resolve_default_bot(level_name: str) -> str | None:
    try:
        level = create_level(level_name)
    except Exception:
        return None
    default_bot = getattr(level, "default_bot_name", None)
    if not isinstance(default_bot, str):
        return None
    default_bot = default_bot.strip()
    return default_bot if default_bot else None


def _resolve_run_bot_name(config: RunConfig, level) -> str | None:
    if config.bot_name:
        return config.bot_name
    default_bot = getattr(level, "default_bot_name", None)
    if not isinstance(default_bot, str):
        return None
    default_bot = default_bot.strip()
    return default_bot if default_bot else None


def _resolve_level_scenarios(level_name: str) -> list[str]:
    try:
        level = create_level(level_name)
    except Exception:
        return []
    list_scenarios = getattr(level, "list_batch_scenarios", None)
    if not callable(list_scenarios):
        return []
    out = [str(name).strip() for name in list_scenarios()]
    return [name for name in out if name]


def _set_eval_scenario(level, name: str | None) -> None:
    if name is None:
        return
    set_scenario = getattr(level, "set_eval_scenario", None)
    if not callable(set_scenario):
        level_type_name = type(level).__name__
        raise ValueError(f"Level '{level_type_name}' does not support scenario selection")
    set_scenario(name)
    return


def _resolve_scenarios_for_config(config: RunConfig, level_name: str) -> list[str]:
    if config.batch_scenarios:
        return _parse_name_csv(config.batch_scenarios)
    if config.scenario_name:
        return [config.scenario_name]
    return _resolve_level_scenarios(level_name)


def _resolve_batch_plan(config: RunConfig) -> tuple[list[int], list[str]]:
    if config.quick_benchmark:
        seeds = [0, 1, 2]
        levels = _list_wave1_levels() or [config.level_name]
        return seeds, levels

    seeds: list[int]
    if config.batch_seeds:
        seeds = _parse_seed_spec(config.batch_seeds)
    elif config.seed is not None:
        seeds = [config.seed]
    else:
        seeds = [0]

    levels: list[str]
    if config.batch_levels:
        levels = _parse_name_csv(config.batch_levels)
    else:
        levels = [config.level_name]
    return seeds, levels


def _configure_level(level, config: RunConfig) -> None:
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


def _run_once(
    config: RunConfig,
    *,
    seed: int | None = None,
    level_name: str | None = None,
    eval_scenario_name: str | None = None,
    print_results: bool = True,
) -> dict[str, Any]:
    run_name = level_name or config.level_name
    level = create_level(run_name)
    chosen_scenario = eval_scenario_name
    if chosen_scenario is None and not _is_batch_mode(config):
        chosen_scenario = config.scenario_name
    _set_eval_scenario(level, chosen_scenario)
    _configure_level(level, config)
    run_bot_name = _resolve_run_bot_name(config, level)
    bot = create_bot(run_bot_name) if run_bot_name is not None else None
    if config.bot_behavior is not None:
        if bot is None:
            raise ValueError("Bot behavior requires a bot (explicit --bot or level default)")
        set_behavior = getattr(bot, "set_behavior", None)
        if not callable(set_behavior):
            raise ValueError(
                f"Bot '{run_bot_name}' does not support --bot-behavior"
            )
        set_behavior(config.bot_behavior)
    game = LanderGame(seed=seed, bot=bot, headless=config.headless, level=level)
    result = game.run(
        print_freq=config.print_freq,
        max_time=config.max_time,
        max_steps=config.max_steps,
    )
    if run_bot_name is not None:
        result["_bot_name"] = run_bot_name
    if config.bot_behavior is not None:
        result["_bot_behavior"] = config.bot_behavior
    result["_level_name"] = run_name
    result["_scenario_name"] = getattr(level, "scenario_name", run_name)
    if config.headless and print_results:
        _print_headless_results(result)
    return result


def _run_once_record(
    config: RunConfig,
    *,
    seed: int | None,
    level_name: str,
    eval_scenario_name: str | None = None,
) -> dict[str, Any]:
    result = _run_once(
        config,
        seed=seed,
        level_name=level_name,
        eval_scenario_name=eval_scenario_name,
        print_results=False,
    )
    record_bot_name = str(result.get("_bot_name") or config.bot_name or "none")
    record_bot_behavior = result.get("_bot_behavior") or config.bot_behavior
    if record_bot_behavior:
        record_bot_name = f"{record_bot_name}:{record_bot_behavior}"
    record_name = str(result.get("_level_name") or level_name)
    record_scenario_name = str(result.get("_scenario_name") or record_name)
    return normalize_run_result(
        bot_name=record_bot_name,
        level_name=record_name,
        scenario=record_scenario_name,
        seed=seed,
        result=result,
    )


def _run_batch_sequential(
    config: RunConfig,
    run_plan: list[tuple[int, str, str | None]],
) -> list[dict[str, Any]]:
    total = len(run_plan)
    records: list[dict[str, Any]] = []
    for run_idx, (seed, level_name, scenario_name) in enumerate(run_plan, start=1):
        if scenario_name is not None:
            print(
                f"[{run_idx}/{total}] seed={seed} level={level_name} scenario={scenario_name}"
            )
        else:
            print(f"[{run_idx}/{total}] seed={seed} level={level_name}")
        records.append(
            _run_once_record(
                config,
                seed=seed,
                level_name=level_name,
                eval_scenario_name=scenario_name,
            )
        )
    return records


def _print_batch_summary(
    summary: dict[str, Any],
    failures: list[dict[str, Any]],
    json_path,
    csv_path,
) -> None:
    def _print_efficiency_block(title: str, block: dict[str, Any] | None) -> None:
        if not block:
            return
        print(f"\n{title}:")
        metric_order = (
            "distance_flown",
            "landing_offset",
            "avg_speed",
            "fuel_consumed",
            "fuel_per_distance",
            "path_efficiency",
            "time",
            "time_to_first_land",
        )
        printed = 0
        for metric in metric_order:
            stats = block.get(metric)
            if not isinstance(stats, dict):
                continue
            count = int(stats.get("count", 0) or 0)
            if count <= 0:
                continue
            mean = float(stats.get("mean", 0.0) or 0.0)
            median = float(stats.get("median", 0.0) or 0.0)
            p90 = float(stats.get("p90", 0.0) or 0.0)
            print(
                f"  - {metric}: n={count} mean={mean:.2f} "
                f"median={median:.2f} p90={p90:.2f}"
            )
            printed += 1
        if printed == 0:
            print("  (no data)")

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
    _print_efficiency_block("Efficiency (successful runs)", summary.get("efficiency_success"))
    _print_efficiency_block("Efficiency (all runs)", summary.get("efficiency_all"))
    if summary.get("by_scenario"):
        print("\nPer-scenario:")
        for name in sorted(summary["by_scenario"]):
            row = summary["by_scenario"][name]
            print(
                f"  - {name}: runs={row['runs']} landed={row['landed']} "
                f"crashed={row['crashed']} success={row['success_rate']:.2%}"
            )
            success_eff = row.get("efficiency_success") or {}
            fuel_stats = success_eff.get("fuel_consumed", {})
            time_stats = success_eff.get("time", {})
            fuel_mean = float(fuel_stats.get("mean", 0.0) or 0.0)
            time_mean = float(time_stats.get("mean", 0.0) or 0.0)
            fuel_count = int(fuel_stats.get("count", 0) or 0)
            if fuel_count > 0:
                print(f"      efficiency_success: fuel_mean={fuel_mean:.2f} time_mean={time_mean:.2f}")
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
    batch_bot_name = config.bot_name or "level_default"
    if config.bot_behavior:
        batch_bot_name = f"{batch_bot_name}:{config.bot_behavior}"
    if not config.headless:
        raise ValueError("Batch mode requires --headless")

    seeds, levels = _resolve_batch_plan(config)
    if not seeds:
        raise ValueError("Batch mode resolved no seeds")
    if not levels:
        raise ValueError("Batch mode resolved no levels")

    run_plan: list[tuple[int, str, str | None]] = []
    for level_name in levels:
        scenarios = _resolve_scenarios_for_config(config, level_name)
        if not scenarios:
            run_plan.extend((seed, level_name, None) for seed in seeds)
            continue
        for scenario_name in scenarios:
            run_plan.extend((seed, level_name, scenario_name) for seed in seeds)
    total = len(run_plan)
    if total <= 0:
        raise ValueError("Batch mode resolved no runs")
    if config.bot_name is None:
        missing_defaults = [
            level_name for level_name in levels if _resolve_default_bot(level_name) is None
        ]
        if missing_defaults:
            missing_csv = ",".join(missing_defaults)
            raise ValueError(
                "Batch mode requires a bot name when levels have no default bot: "
                f"{missing_csv}"
            )

    worker_count = max(1, min(config.batch_workers, total, os.cpu_count() or 1))
    print(f"Batch workers: requested={config.batch_workers} effective={worker_count}")

    if worker_count <= 1:
        records = _run_batch_sequential(config, run_plan)
    else:
        indexed_records: dict[int, dict[str, Any]] = {}
        try:
            with ProcessPoolExecutor(max_workers=worker_count) as pool:
                future_map = {}
                for run_idx, (seed, level_name, scenario_name) in enumerate(
                    run_plan, start=1
                ):
                    fut = pool.submit(
                        _run_once_record,
                        config,
                        seed=seed,
                        level_name=level_name,
                        eval_scenario_name=scenario_name,
                    )
                    future_map[fut] = (run_idx, seed, level_name, scenario_name)
                done = 0
                for fut in as_completed(future_map):
                    run_idx, seed, level_name, scenario_name = future_map[fut]
                    try:
                        record = fut.result()
                    except Exception as exc:
                        scenario_label = (
                            f" scenario={scenario_name}" if scenario_name is not None else ""
                        )
                        raise RuntimeError(
                            f"run {run_idx}/{total} seed={seed} level={level_name} "
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
            records = _run_batch_sequential(config, run_plan)

    summary = aggregate_eval_records(records)
    failed = [r for r in records if not r.get("success", False)]

    json_path = None
    csv_path = None
    if config.batch_json:
        json_target = (
            default_artifact_path(
                kind="json",
                level_name=config.level_name,
                bot_name=batch_bot_name,
                seeds=seeds,
                scenarios=levels,
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
                bot_name=batch_bot_name,
                seeds=seeds,
                scenarios=levels,
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

    default_bot_name = _resolve_default_bot(config.level_name)
    if config.headless and not (config.bot_name or default_bot_name):
        parser.error("Headless mode requires a bot name or a level default bot")
    if _is_batch_mode(config):
        try:
            exit_code = _run_batch(config)
            raise SystemExit(exit_code)
        except ValueError as exc:
            parser.error(str(exc))

    print(f"Using level {config.level_name}")
    if config.bot_name is not None:
        print(f"Running with bot {config.bot_name}")
    elif default_bot_name is not None:
        print(f"Running with bot {default_bot_name} (level default)")
    if config.bot_behavior is not None:
        print(f"Using bot behavior {config.bot_behavior}")

    try:
        result = _run_once(
            config,
            seed=config.seed,
            print_results=config.headless,
        )
    except ValueError as exc:
        parser.error(str(exc))
    _ = result


if __name__ == "__main__":
    main()
