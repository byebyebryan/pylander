"""Main entrypoint for lunar lander game."""

from __future__ import annotations

from app.cli import announce_command, parse_command
from app.config import BenchCommand, RunCommand
from app.run_batch import run_benchmark
from app.run_single import resolve_default_bot, run_once


def main() -> None:
    parser, command = parse_command()
    announce_command(command)

    if isinstance(command, BenchCommand):
        try:
            exit_code = run_benchmark(command.bench)
            raise SystemExit(exit_code)
        except ValueError as exc:
            parser.error(str(exc))

    if isinstance(command, RunCommand):
        cfg = command.run
        try:
            if cfg.headless:
                default_bot_name = resolve_default_bot(cfg.level_name)
                if not (cfg.bot_name or default_bot_name):
                    parser.error("Headless run requires a bot name or a level default bot")
                if cfg.bot_name is None and default_bot_name is not None:
                    print(f"Using level-default bot: {default_bot_name}")
            run_once(
                cfg,
                seed=cfg.seed,
                print_results=cfg.headless,
            )
        except ValueError as exc:
            parser.error(str(exc))
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
