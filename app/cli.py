from __future__ import annotations

import argparse
import os

from bots import list_available_bots
from landers import list_available_landers
from levels import list_available_levels

from app.config import BenchCommand, BenchSettings, Command, PlayCommand, RunCommand, RunSettings


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}:\n  (none)"
    joined = "\n  ".join(items)
    return f"{title}:\n  {joined}"


def _default_level(levels: list[str]) -> str | None:
    return "flat" if "flat" in levels else (levels[0] if levels else None)


def _add_common_run_args(
    parser: argparse.ArgumentParser,
    *,
    levels: list[str],
    bots: list[str],
    landers: list[str],
    default_level: str | None,
    include_freq: bool,
) -> None:
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
    if include_freq:
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
        help="Limit simulation to N steps",
    )
    parser.add_argument(
        "--time",
        type=float,
        default=None,
        help="Limit simulation to S seconds (default: 300)",
    )
    parser.add_argument(
        "--plot",
        choices=("none", "speed", "thrust", "all"),
        default=None,
        help="Trajectory plot mode",
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
    parser.add_argument(
        "--eval-mode",
        choices=("auto", "focused", "full"),
        default="auto",
        help="Evaluation mode for levels that support staged scoring",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Run a specific scenario for levels that support scenario selection",
    )
    parser.add_argument("--lander", choices=landers, help="Choose lander variant")


def build_parser() -> argparse.ArgumentParser:
    levels = list_available_levels()
    bots = list_available_bots()
    landers = list_available_landers()
    default_level = _default_level(levels)

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

    sub = parser.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="Interactive play mode (rendered)")
    _add_common_run_args(
        play,
        levels=levels,
        bots=bots,
        landers=landers,
        default_level=default_level,
        include_freq=False,
    )

    run = sub.add_parser("run", help="Single headless run")
    _add_common_run_args(
        run,
        levels=levels,
        bots=bots,
        landers=landers,
        default_level=default_level,
        include_freq=True,
    )

    bench = sub.add_parser("bench", help="Headless benchmark batch")
    bench.add_argument(
        "level_name",
        nargs="?",
        default=default_level,
        choices=levels,
        help=f"Primary level name (default: {default_level})",
    )
    bench.add_argument("--bot", dest="bot", choices=bots, default=None)
    bench.add_argument("--levels", type=str, default=None, help="Comma-separated level list")
    bench.add_argument("--seeds", type=str, default=None, help="Seed spec, e.g. 0-19 or 0,1,2")
    bench.add_argument(
        "--scenarios",
        type=str,
        default=None,
        help="Comma-separated scenario list for all benchmarked levels",
    )
    bench.add_argument("--scenario", type=str, default=None, help="Single scenario for all levels")
    bench.add_argument("--lander", choices=landers)
    bench.add_argument(
        "--eval-mode",
        choices=("auto", "focused", "full"),
        default="auto",
        help="Evaluation mode for levels that support staged scoring",
    )
    bench.add_argument("--quick", action="store_true", help="Small fixed regression preset")
    bench.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Batch worker processes (default: CPU count)",
    )
    bench.add_argument("--steps", type=int, default=None, help="Limit simulation to N steps")
    bench.add_argument("--time", type=float, default=None, help="Limit simulation to S seconds")
    bench.add_argument(
        "--plot",
        choices=("none", "speed", "thrust", "all"),
        default="none",
        help="Plot mode for headless runs",
    )
    bench.add_argument("--json", type=str, default=None, help="Write report JSON path (or 'auto')")
    bench.add_argument("--csv", type=str, default=None, help="Write report CSV path (or 'auto')")

    return parser


def _build_run_settings(args: argparse.Namespace, *, headless: bool) -> RunSettings:
    if headless:
        print_freq = 60 if args.freq is None else int(args.freq)
    else:
        print_freq = 60

    return RunSettings(
        level_name=args.level_name,
        bot_name=args.bot,
        seed=args.seed,
        scenario_name=(args.scenario.strip() if args.scenario else None),
        lander_name=args.lander,
        eval_mode=str(getattr(args, "eval_mode", "auto") or "auto"),
        print_freq=print_freq,
        max_time=300.0 if args.time is None else float(args.time),
        max_steps=args.steps,
        plot_mode="none" if args.plot is None else args.plot,
        stop_on_crash=bool(args.stop_on_crash),
        stop_on_out_of_fuel=bool(args.stop_on_out_of_fuel),
        stop_on_first_land=bool(args.stop_on_first_land),
        headless=headless,
    )


def parse_command(argv: list[str] | None = None) -> tuple[argparse.ArgumentParser, Command]:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "play":
        return parser, PlayCommand(run=_build_run_settings(args, headless=False))

    if args.command == "run":
        return parser, RunCommand(run=_build_run_settings(args, headless=True))

    if args.command == "bench":
        workers = (
            max(1, int(args.workers))
            if args.workers is not None
            else max(1, int(os.cpu_count() or 1))
        )
        bench_cfg = BenchSettings(
            bot_name=args.bot,
            level_name=args.level_name,
            level_names_csv=args.levels,
            seeds_csv=args.seeds,
            scenarios_csv=args.scenarios,
            scenario_name=(args.scenario.strip() if args.scenario else None),
            lander_name=args.lander,
            eval_mode=str(args.eval_mode or "auto"),
            quick=bool(args.quick),
            workers=workers,
            max_time=300.0 if args.time is None else float(args.time),
            max_steps=args.steps,
            plot_mode=args.plot,
            json_path=args.json,
            csv_path=args.csv,
        )
        return parser, BenchCommand(bench=bench_cfg)

    raise AssertionError(f"Unsupported command {args.command!r}")


def announce_command(command: Command) -> None:
    if isinstance(command, PlayCommand):
        print("Mode: interactive play")
        _print_run_summary(command.run)
        return
    if isinstance(command, RunCommand):
        print("Mode: headless run")
        _print_run_summary(command.run)
        return
    if isinstance(command, BenchCommand):
        print("Mode: benchmark")
        cfg = command.bench
        print(f"Primary level: {cfg.level_name}")
        if cfg.level_names_csv:
            print(f"Levels: {cfg.level_names_csv}")
        if cfg.seeds_csv:
            print(f"Seeds: {cfg.seeds_csv}")
        if cfg.scenarios_csv:
            print(f"Scenarios: {cfg.scenarios_csv}")
        if cfg.scenario_name:
            print(f"Scenario: {cfg.scenario_name}")
        if cfg.quick:
            print("Quick preset: enabled")
        print(f"Workers requested: {cfg.workers}")
        print(f"Eval mode: {cfg.eval_mode}")
        if cfg.lander_name:
            print(f"Lander: {cfg.lander_name}")
        return


def _print_run_summary(cfg: RunSettings) -> None:
    print(f"Level: {cfg.level_name}")
    if cfg.bot_name:
        print(f"Bot: {cfg.bot_name}")
    if cfg.seed is not None:
        print(f"Seed: {cfg.seed}")
    if cfg.scenario_name:
        print(f"Scenario: {cfg.scenario_name}")
    if cfg.eval_mode != "auto":
        print(f"Eval mode: {cfg.eval_mode}")
    if cfg.lander_name:
        print(f"Lander: {cfg.lander_name}")
    if cfg.headless:
        print(f"Print freq: {cfg.print_freq}")
        print(f"Max time: {cfg.max_time:.1f}s")
        if cfg.max_steps is not None:
            print(f"Max steps: {cfg.max_steps}")
        print(f"Plot: {cfg.plot_mode}")
