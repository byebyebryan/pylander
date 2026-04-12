"""Main entrypoint for lunar lander game."""

from __future__ import annotations

from app.cli import announce_command, parse_command
from bot_framework.config import BenchCommand, RunCommand
from bot_framework.run_batch import run_benchmark
from app.run_single import resolve_default_bot, run_once
from game.runtime.runtime_adapter import make_runtime_adapter


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
                    parser.error(
                        "Headless run requires a bot name or a level default bot"
                    )
                if cfg.bot_name is None and default_bot_name is not None:
                    print(f"Using level-default bot: {default_bot_name}")
                run_once(
                    cfg,
                    seed=cfg.seed,
                    print_results=cfg.headless,
                )
            else:
                from game.game_host import GameHost
                from game.levels.registry import create_level
                from game import LanderGame

                def create_desktop_session(level_name, seed, width, height):
                    level = create_level(level_name)
                    return LanderGame(
                        level=level,
                        seed=seed,
                        width=width,
                        height=height,
                        headless=False,
                        runtime_adapter=make_runtime_adapter(bot=None, headless=False),
                    )

                host = GameHost(
                    session_factory=create_desktop_session,
                    skip_title=cfg.skip_title,
                    level_name=cfg.level_name,
                    seed=cfg.seed,
                )
                host.run()
        except ValueError as exc:
            parser.error(str(exc))
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
