"""Main entry point for lunar lander game (thin wrapper)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from game import LanderGame
from bots import create_bot, list_available_bots
from levels import create_level, list_available_levels
from landers import list_available_landers


@dataclass
class RunConfig:
    level_name: str
    bot_name: str | None
    headless: bool
    print_freq: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    stop_on_crash: bool
    stop_on_out_of_fuel: bool
    stop_on_first_land: bool
    seed: int | None
    lander_name: str | None


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
    return parser


def _parse_args(args: argparse.Namespace) -> RunConfig:
    print_freq = 60 if args.freq is None else args.freq
    max_time = 300.0 if args.time is None else args.time
    plot_mode = "none" if args.plot is None else args.plot

    return RunConfig(
        level_name=args.level_name,
        bot_name=args.bot_name,
        headless=args.headless,
        print_freq=print_freq,
        max_time=max_time,
        max_steps=args.steps,
        plot_mode=plot_mode,
        stop_on_crash=args.stop_on_crash,
        stop_on_out_of_fuel=args.stop_on_out_of_fuel,
        stop_on_first_land=args.stop_on_first_land,
        seed=args.seed,
        lander_name=args.lander,
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


def main() -> None:
    """Entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    config = _parse_args(args)

    _announce_config(config, args)

    if config.headless and not config.bot_name:
        parser.error("Headless mode requires a bot name")

    level = create_level(config.level_name)
    print(f"Using level {config.level_name}")

    bot = None
    if config.bot_name is not None:
        bot = create_bot(config.bot_name)
        print(f"Running with bot {config.bot_name}")

    if config.headless:
        config.stop_on_out_of_fuel = True
        config.stop_on_crash = True
        config.stop_on_first_land = True

    level.stop_on_crash = config.stop_on_crash
    level.stop_on_out_of_fuel = config.stop_on_out_of_fuel
    level.stop_on_first_land = config.stop_on_first_land
    level.plot_mode = config.plot_mode
    level.max_time = config.max_time

    if config.lander_name:
        setattr(level, "lander_name", config.lander_name)

    game = LanderGame(seed=config.seed, bot=bot, headless=config.headless, level=level)
    result = game.run(
        print_freq=config.print_freq,
        max_time=config.max_time,
        max_steps=config.max_steps,
    )

    if config.headless:
        _print_headless_results(result)


if __name__ == "__main__":
    main()
