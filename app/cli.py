from __future__ import annotations

import argparse
import os

from app.config import BenchCommand, BenchSettings, BenchTarget, Command, RunCommand, RunSettings
from bots import list_available_bots
from landers import list_available_landers
from app.selector import parse_seed_spec, parse_selector, render_selector
from core.trace_policy import (
    TRACE_DETAIL_DEBUG,
    TRACE_DETAIL_MODES,
    TRACE_DETAIL_REPORT,
    normalize_trace_detail,
)
from levels.registry import (
    expand_selector_bindings,
    list_public_levels,
    resolve_selector_binding,
)


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
        help="Run selector: level[:layer[:...]][:goal[:seed]]",
    )
    parser.add_argument(
        "-b",
        "--bot",
        dest="bot",
        default=None,
        help="Bot name (overrides level default bot)",
    )
    parser.add_argument(
        "--bot-config",
        type=str,
        default=None,
        help="Path to JSON bot override config (supported bots only)",
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
        "--trace",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable structured trace capture for this run",
    )
    parser.add_argument(
        "--trace-sample-period-s",
        type=float,
        default=None,
        help="Trace sampling period in seconds (default: 0.25 when tracing is enabled)",
    )
    parser.add_argument(
        "--trace-detail",
        choices=TRACE_DETAIL_MODES,
        default=None,
        help="Trace detail level when tracing is enabled",
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
        "-l", "--lander", help="Choose lander variant"
    )


def build_parser() -> argparse.ArgumentParser:
    levels = list_public_levels()
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

    play = sub.add_parser("play", help="Rendered interactive play session")
    _add_common_run_args(play, include_freq=True)

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

    plot = sub.add_parser("plot", help="Headless simulation with trace capture enabled")
    _add_common_run_args(plot, include_freq=True)

    bench = sub.add_parser("bench", help="Headless benchmark batch")
    bench.add_argument(
        "selectors",
        nargs="+",
        help="Benchmark selectors: level[:layer[:...]][:goal[:seed_spec]]",
    )
    bench.add_argument("-b", "--bot", dest="bot", default=None)
    bench.add_argument(
        "--bot-config",
        type=str,
        default=None,
        help="Path to JSON bot override config (supported bots only)",
    )
    bench.add_argument("-l", "--lander")
    bench.add_argument("-n", "--steps", type=int, default=None, help="Limit simulation to N steps")
    bench.add_argument("-t", "--time", type=float, default=None, help="Limit simulation to S seconds")
    bench.add_argument(
        "--trace-sample-period-s",
        type=float,
        default=0.25,
        help="Trace sampling period in seconds for benchmark capture",
    )
    bench.add_argument(
        "--trace-detail",
        choices=TRACE_DETAIL_MODES,
        default=TRACE_DETAIL_REPORT,
        help="Trace detail level for benchmark capture",
    )
    bench.add_argument(
        "-j",
        "--json",
        type=str,
        default="auto",
        help="Write tracepack JSON path (or 'auto')",
    )
    bench.add_argument(
        "--bot-profile",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable bot compute profiling during benchmark runs (default: on)",
    )
    bench.add_argument(
        "--bot-profile-interval-s",
        type=float,
        default=None,
        help="Profiler report interval in seconds (when profiler logs are enabled)",
    )
    bench.add_argument(
        "--bot-profile-logs",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable periodic profiler console logs during benchmark runs (default: off)",
    )

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
    default_trace_enabled: bool,
    default_trace_detail: str,
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
    try:
        binding = resolve_selector_binding(
            selector.level_name,
            selector.scenario_path,
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

    trace_enabled = default_trace_enabled if args.trace is None else bool(args.trace)
    trace_sample_period_s = (
        0.25
        if args.trace_sample_period_s is None
        else max(0.05, float(args.trace_sample_period_s))
    )
    trace_detail = normalize_trace_detail(args.trace_detail, default=default_trace_detail)
    return RunSettings(
        level_name=binding.level_name,
        runtime_level_name=binding.runtime_level_name,
        bot_name=args.bot,
        bot_config_path=args.bot_config,
        seed=seed_value,
        scenario_name=binding.scenario_name,
        runtime_scenario_name=binding.runtime_scenario_name,
        eval_goal=selector.goal or "landing",
        lander_name=args.lander,
        print_freq=print_freq,
        max_time=300.0 if args.time is None else float(args.time),
        max_steps=args.steps,
        trace_enabled=trace_enabled,
        trace_sample_period_s=trace_sample_period_s,
        trace_detail=trace_detail,
        trace_root_dir=None,
        stop_on_crash=bool(args.stop_on_crash),
        stop_on_out_of_fuel=bool(args.stop_on_out_of_fuel),
        stop_on_first_land=bool(args.stop_on_first_land),
        headless=headless,
        bot_profile_enabled=None,
        bot_profile_interval_s=None,
        bot_profile_log_lines=None,
    )


def parse_command(argv: list[str] | None = None) -> tuple[argparse.ArgumentParser, Command]:
    parser = build_parser()
    args = parser.parse_args(argv)

    levels_list = list_public_levels()
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

    if args.command == "play":
        return parser, RunCommand(
            run=_build_run_settings(
                parser,
                args,
                levels=levels,
                default_level=default_level,
                headless=False,
                default_trace_enabled=False,
                default_trace_detail=TRACE_DETAIL_REPORT,
            )
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
                default_trace_enabled=False,
                default_trace_detail=TRACE_DETAIL_REPORT,
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
                default_trace_enabled=False,
                default_trace_detail=TRACE_DETAIL_REPORT,
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
                default_trace_enabled=True,
                default_trace_detail=TRACE_DETAIL_DEBUG,
            )
        )

    if args.command == "bench":
        workers = _default_bench_workers()
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
            try:
                expand_selector_bindings(
                    parsed.level_name,
                    scenario_path=parsed.scenario_path,
                    allow_wildcards=True,
                )
            except ValueError as exc:
                parser.error(str(exc))
            selectors.append(
                BenchTarget(
                    level_name=parsed.level_name,
                    scenario_name=parsed.scenario_name,
                    seed_spec=parsed.seed_token,
                    scenario_path=parsed.scenario_path,
                    eval_goal=parsed.goal or "landing",
                )
            )
        bench_cfg = BenchSettings(
            bot_name=args.bot,
            bot_config_path=args.bot_config,
            selectors=tuple(selectors),
            lander_name=args.lander,
            workers=workers,
            max_time=300.0 if args.time is None else float(args.time),
            max_steps=args.steps,
            trace_enabled=True,
            trace_sample_period_s=max(0.05, float(args.trace_sample_period_s)),
            trace_detail=normalize_trace_detail(args.trace_detail, default=TRACE_DETAIL_REPORT),
            json_path=args.json,
            bot_profile_enabled=bool(args.bot_profile),
            bot_profile_interval_s=(
                None
                if args.bot_profile_interval_s is None
                else max(0.25, float(args.bot_profile_interval_s))
            ),
            bot_profile_log_lines=bool(args.bot_profile_logs),
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
        if cfg.bot_config_path:
            print(f"Bot config: {cfg.bot_config_path}")
        print(f"Trace capture: {'on' if cfg.trace_enabled else 'off'}")
        if cfg.trace_enabled:
            print(f"Trace sample period: {cfg.trace_sample_period_s:.2f}s")
            print(f"Trace detail: {cfg.trace_detail}")
        print(f"Bot profile: {'on' if cfg.bot_profile_enabled else 'off'}")
        print(f"Bot profile logs: {'on' if cfg.bot_profile_log_lines else 'off'}")
        if cfg.bot_profile_interval_s is not None:
            print(f"Bot profile interval: {cfg.bot_profile_interval_s:.2f}s")
        if cfg.lander_name:
            print(f"Lander: {cfg.lander_name}")
        return


def _render_bench_target(target: BenchTarget) -> str:
    return render_selector(
        level_name=target.level_name,
        scenario_name=target.scenario_name,
        goal=target.eval_goal,
        seed_token=target.seed_spec,
    )


def _print_run_summary(cfg: RunSettings) -> None:
    selector = render_selector(
        level_name=cfg.level_name,
        scenario_name=cfg.scenario_name,
        goal=cfg.eval_goal,
        seed_token=cfg.seed,
    )
    print(f"Selector: {selector}")
    if cfg.bot_name:
        print(f"Bot: {cfg.bot_name}")
    if cfg.bot_config_path:
        print(f"Bot config: {cfg.bot_config_path}")
    if cfg.lander_name:
        print(f"Lander: {cfg.lander_name}")
    if cfg.headless:
        print(f"Print freq: {cfg.print_freq}")
        print(f"Max time: {cfg.max_time:.1f}s")
        if cfg.max_steps is not None:
            print(f"Max steps: {cfg.max_steps}")
        print(f"Trace capture: {'on' if cfg.trace_enabled else 'off'}")
        if cfg.trace_enabled:
            print(f"Trace sample period: {cfg.trace_sample_period_s:.2f}s")
            print(f"Trace detail: {cfg.trace_detail}")
