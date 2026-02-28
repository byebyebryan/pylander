from __future__ import annotations

from typing import Any

from bots import create_bot
from core.eval import normalize_run_result
from game import LanderGame
from levels import create_level

from app.config import RunSettings
from app.reporting import print_headless_results


def resolve_default_bot(level_name: str) -> str | None:
    try:
        level = create_level(level_name)
    except Exception:
        return None
    default_bot = getattr(level, "default_bot_name", None)
    if not isinstance(default_bot, str):
        return None
    default_bot = default_bot.strip()
    return default_bot if default_bot else None


def resolve_run_bot_name(settings: RunSettings, level) -> str | None:
    if settings.bot_name:
        return settings.bot_name
    default_bot = getattr(level, "default_bot_name", None)
    if not isinstance(default_bot, str):
        return None
    default_bot = default_bot.strip()
    return default_bot if default_bot else None


def set_eval_scenario(level, name: str | None) -> None:
    if name is None:
        return
    set_scenario = getattr(level, "set_eval_scenario", None)
    if not callable(set_scenario):
        level_type_name = type(level).__name__
        raise ValueError(f"Level '{level_type_name}' does not support scenario selection")
    set_scenario(name)


def configure_level(level, settings: RunSettings, *, benchmark_mode: str | None = None) -> None:
    stop_on_crash = settings.stop_on_crash
    stop_on_out_of_fuel = settings.stop_on_out_of_fuel
    stop_on_first_land = settings.stop_on_first_land
    if settings.headless:
        stop_on_crash = True
        stop_on_out_of_fuel = True
        stop_on_first_land = True

    level.stop_on_crash = stop_on_crash
    level.stop_on_out_of_fuel = stop_on_out_of_fuel
    level.stop_on_first_land = stop_on_first_land

    set_benchmark_mode = getattr(level, "set_benchmark_mode", None)
    if callable(set_benchmark_mode) and benchmark_mode is not None:
        set_benchmark_mode(benchmark_mode)

    set_eval_mode = getattr(level, "set_eval_mode", None)
    if callable(set_eval_mode):
        set_eval_mode(settings.eval_mode)
    elif settings.eval_mode != "auto":
        level_type_name = type(level).__name__
        raise ValueError(
            f"Level '{level_type_name}' does not support --eval-mode {settings.eval_mode!r}"
        )

    level.plot_mode = settings.plot_mode
    level.max_time = settings.max_time
    if settings.lander_name:
        setattr(level, "lander_name", settings.lander_name)


def run_once(
    settings: RunSettings,
    *,
    seed: int | None = None,
    level_name: str | None = None,
    eval_scenario_name: str | None = None,
    print_results: bool = True,
    benchmark_mode: str | None = None,
) -> dict[str, Any]:
    run_name = level_name or settings.level_name
    level = create_level(run_name)

    chosen_scenario = eval_scenario_name if eval_scenario_name is not None else settings.scenario_name
    set_eval_scenario(level, chosen_scenario)
    configure_level(level, settings, benchmark_mode=benchmark_mode)

    run_bot_name = resolve_run_bot_name(settings, level)
    bot = create_bot(run_bot_name) if run_bot_name is not None else None
    if bot is not None and run_bot_name is not None:
        setattr(bot, "_bot_name", run_bot_name)

    game = LanderGame(seed=seed, bot=bot, headless=settings.headless, level=level)
    result = game.run(
        print_freq=settings.print_freq,
        max_time=settings.max_time,
        max_steps=settings.max_steps,
    )

    if run_bot_name is not None:
        result["_bot_name"] = run_bot_name
    result["_level_name"] = run_name
    result["_scenario_name"] = getattr(level, "scenario_name", run_name)

    if settings.headless and print_results:
        print_headless_results(result)
    return result


def run_once_record(
    settings: RunSettings,
    *,
    seed: int | None,
    level_name: str,
    eval_scenario_name: str | None = None,
    benchmark_mode: str | None = None,
) -> dict[str, Any]:
    result = run_once(
        settings,
        seed=seed,
        level_name=level_name,
        eval_scenario_name=eval_scenario_name,
        print_results=False,
        benchmark_mode=benchmark_mode,
    )
    record_bot_name = str(result.get("_bot_name") or settings.bot_name or "none")
    record_level_name = str(result.get("_level_name") or level_name)
    record_scenario_name = str(result.get("_scenario_name") or record_level_name)
    return normalize_run_result(
        bot_name=record_bot_name,
        level_name=record_level_name,
        scenario=record_scenario_name,
        seed=seed,
        result=result,
    )
