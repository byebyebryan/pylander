from __future__ import annotations

import argparse
import os

from bots import list_available_bots
from landers import list_available_landers
from levels import list_available_levels

from app.config import BenchCommand, BenchSettings, BenchTarget, Command, RunCommand, RunSettings
from app.selector import parse_seed_spec, parse_selector


def _format_list(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}:\n  (none)"
    joined = "\n  ".join(items)
    return f"{title}:\n  {joined}"


def _default_level(levels: list[str]) -> str | None:
    return "flat" if "flat" in levels else (levels[0] if levels else None)


def _default_bench_workers() -> int:
    cpu_count = int(os.cpu_count() or 1)
    return max(1, cpu_count - 2)


def _add_common_run_args(
    parser: argparse.ArgumentParser,
    *,
    include_freq: bool,
) -> None:
    parser.add_argument(
        "selector",
        nargs="?",
        default=None,
        help="Run selector: level[:scenario[:seed]]",
    )
    parser.add_argument(
        "-b",
        "--bot",
        dest="bot",
        default=None,
        help="Bot name (overrides level default bot)",
    )
    if include_freq:
        parser.add_argument(
            "-f",
            "--freq",
            type=int,
            default=None,
            help="Print stats every N frames (60=1/sec, 1=every frame, 0=off)",
        )
    parser.add_argument(
        "-n",
        "--steps",
        type=int,
        default=None,
        help="Limit simulation to N steps",
    )
    parser.add_argument(
        "-t",
        "--time",
        type=float,
        default=None,
        help="Limit simulation to S seconds (default: 300)",
    )
    parser.add_argument(
        "-p",
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
        "-e",
        "--eval-mode",
        choices=("auto", "focused", "full"),
        default="auto",
        help="Evaluation mode for levels that support staged scoring",
    )
    parser.add_argument("-l", "--lander", help="Choose lander variant")


def build_parser() -> argparse.ArgumentParser:
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

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Single run (headless by default)")
    _add_common_run_args(run, include_freq=True)
    run.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Enable rendered interactive mode",
    )

    sim = sub.add_parser("sim", help="Single headless simulation run")
    _add_common_run_args(sim, include_freq=True)

    plot = sub.add_parser("plot", help="Headless simulation with plotting enabled")
    _add_common_run_args(plot, include_freq=True)

    bench = sub.add_parser("bench", help="Headless benchmark batch")
    bench.add_argument(
        "selectors",
        nargs="+",
        help="Benchmark selectors: level[:scenario[:seed_spec]]",
    )
    bench.add_argument("-b", "--bot", dest="bot", default=None)
    bench.add_argument("-l", "--lander")
    bench.add_argument(
        "-e",
        "--eval-mode",
        choices=("auto", "focused", "full"),
        default="auto",
        help="Evaluation mode for levels that support staged scoring",
    )
    bench.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Batch worker processes (default: CPU count - 2, min 1)",
    )
    bench.add_argument("-n", "--steps", type=int, default=None, help="Limit simulation to N steps")
    bench.add_argument("-t", "--time", type=float, default=None, help="Limit simulation to S seconds")
    bench.add_argument(
        "-p",
        "--plot",
        choices=("none", "speed", "thrust", "all"),
        default="none",
        help="Plot mode for headless runs",
    )
    bench.add_argument("-j", "--json", type=str, default=None, help="Write report JSON path (or 'auto')")
    bench.add_argument("-c", "--csv", type=str, default=None, help="Write report CSV path (or 'auto')")

    return parser


def _validate_bot_lander_choices(
    parser: argparse.ArgumentParser,
    *,
    bot_name: str | None,
    bots: set[str],
    lander_name: str | None,
    landers: set[str],
) -> None:
    if bot_name is not None and bot_name not in bots:
        known = ", ".join(sorted(bots))
        parser.error(f"Unknown bot '{bot_name}'. Expected one of: {known}")
    if lander_name is not None and lander_name not in landers:
        known = ", ".join(sorted(landers))
        parser.error(f"Unknown lander '{lander_name}'. Expected one of: {known}")


def _build_run_settings(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    levels: set[str],
    default_level: str | None,
    headless: bool,
    default_plot_mode: str,
) -> RunSettings:
    if headless:
        print_freq = 60 if args.freq is None else int(args.freq)
    else:
        print_freq = 60

    try:
        selector = parse_selector(
            args.selector,
            default_level=default_level,
            known_levels=levels,
        )
    except ValueError as exc:
        parser.error(str(exc))

    seed_value: int | None = None
    if selector.seed_token is not None:
        try:
            seed_value = int(selector.seed_token)
        except ValueError as exc:
            parser.error(
                f"Invalid selector '{args.selector}': seed must be an integer for sim/run/plot"
            )
            raise AssertionError from exc

    plot_mode = default_plot_mode if args.plot is None else str(args.plot)
    return RunSettings(
        level_name=selector.level_name,
        bot_name=args.bot,
        seed=seed_value,
        scenario_name=selector.scenario_name,
        lander_name=args.lander,
        eval_mode=str(getattr(args, "eval_mode", "auto") or "auto"),
        print_freq=print_freq,
        max_time=300.0 if args.time is None else float(args.time),
        max_steps=args.steps,
        plot_mode=plot_mode,
        stop_on_crash=bool(args.stop_on_crash),
        stop_on_out_of_fuel=bool(args.stop_on_out_of_fuel),
        stop_on_first_land=bool(args.stop_on_first_land),
        headless=headless,
    )


def parse_command(argv: list[str] | None = None) -> tuple[argparse.ArgumentParser, Command]:
    parser = build_parser()
    args = parser.parse_args(argv)

    levels_list = list_available_levels()
    levels = set(levels_list)
    bots = set(list_available_bots())
    landers = set(list_available_landers())
    default_level = _default_level(levels_list)

    bot_name = getattr(args, "bot", None)
    lander_name = getattr(args, "lander", None)
    _validate_bot_lander_choices(
        parser,
        bot_name=bot_name,
        bots=bots,
        lander_name=lander_name,
        landers=landers,
    )

    if args.command == "run":
        headless = not bool(args.interactive)
        return parser, RunCommand(
            run=_build_run_settings(
                parser,
                args,
                levels=levels,
                default_level=default_level,
                headless=headless,
                default_plot_mode="none",
            )
        )

    if args.command == "sim":
        return parser, RunCommand(
            run=_build_run_settings(
                parser,
                args,
                levels=levels,
                default_level=default_level,
                headless=True,
                default_plot_mode="none",
            )
        )

    if args.command == "plot":
        return parser, RunCommand(
            run=_build_run_settings(
                parser,
                args,
                levels=levels,
                default_level=default_level,
                headless=True,
                default_plot_mode="all",
            )
        )

    if args.command == "bench":
        workers = (
            max(1, int(args.workers))
            if args.workers is not None
            else _default_bench_workers()
        )
        selectors: list[BenchTarget] = []
        for raw_selector in args.selectors:
            try:
                parsed = parse_selector(
                    raw_selector,
                    default_level=None,
                    known_levels=levels,
                )
            except ValueError as exc:
                parser.error(str(exc))
            if parsed.seed_token is not None:
                try:
                    seeds = parse_seed_spec(parsed.seed_token)
                except ValueError:
                    parser.error(
                        f"Invalid selector '{raw_selector}': seed spec must use ints/ranges like 0-9"
                    )
                if not seeds:
                    parser.error(f"Invalid selector '{raw_selector}': empty seed spec")
            selectors.append(
                BenchTarget(
                    level_name=parsed.level_name,
                    scenario_name=parsed.scenario_name,
                    seed_spec=parsed.seed_token,
                )
            )
        bench_cfg = BenchSettings(
            bot_name=args.bot,
            selectors=tuple(selectors),
            lander_name=args.lander,
            eval_mode=str(args.eval_mode or "auto"),
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
    if isinstance(command, RunCommand):
        print("Mode: interactive run" if not command.run.headless else "Mode: headless run")
        _print_run_summary(command.run)
        return
    if isinstance(command, BenchCommand):
        print("Mode: benchmark")
        cfg = command.bench
        print(f"Selectors: {', '.join(_render_bench_target(sel) for sel in cfg.selectors)}")
        print(f"Workers requested: {cfg.workers}")
        print(f"Eval mode: {cfg.eval_mode}")
        if cfg.lander_name:
            print(f"Lander: {cfg.lander_name}")
        return


def _render_bench_target(target: BenchTarget) -> str:
    scenario_token = target.scenario_name or ""
    seed_token = target.seed_spec or ""
    if scenario_token and seed_token:
        return f"{target.level_name}:{scenario_token}:{seed_token}"
    if scenario_token:
        return f"{target.level_name}:{scenario_token}"
    if seed_token:
        return f"{target.level_name}::{seed_token}"
    return target.level_name


def _print_run_summary(cfg: RunSettings) -> None:
    selector = cfg.level_name
    if cfg.scenario_name:
        selector = f"{selector}:{cfg.scenario_name}"
    if cfg.seed is not None:
        selector = f"{selector}:{cfg.seed}" if cfg.scenario_name else f"{selector}::{cfg.seed}"
    print(f"Selector: {selector}")
    if cfg.bot_name:
        print(f"Bot: {cfg.bot_name}")
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
