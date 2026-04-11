from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, cast

from game.core.eval_goals import (
    EVAL_GOAL_LANDING,
    normalize_eval_goal,
    normalize_eval_goals,
)
from game.core.eval import normalize_run_result
from game.core.level_capabilities import (
    level_name_tag,
    set_benchmark_mode_checked,
    set_eval_goal_checked,
    set_eval_scenario_checked,
)
from game import LanderGame
from game.runtime.runtime_adapter import make_runtime_adapter

from bot_framework.config import (
    RunSettings,
    resolve_default_bot as _resolve_default_bot,
)
from tooling.reporting import print_headless_results
from game.runtime._level_resolve import _resolve_runtime_binding, create_level_checked


def _create_bot(name: str, *, config_override: dict[str, Any] | None = None):
    from bot_framework.bots import create_bot

    return create_bot(name, config_override=config_override)


def resolve_default_bot(level_name: str) -> str | None:
    from game.levels.registry import is_public_level

    runtime_level_name = level_name
    if is_public_level(level_name):
        runtime_level_name = _resolve_runtime_binding(level_name).runtime_level_name
    return _resolve_default_bot(runtime_level_name)


def resolve_run_bot_name(settings: RunSettings, level) -> str | None:
    if settings.bot_name:
        return str(settings.bot_name).strip()
    level_name = level_name_tag(level)
    base_level = level_name.split(":")[0].strip()
    return _resolve_default_bot(base_level)


def set_eval_scenario(level, name: str | None) -> None:
    set_eval_scenario_checked(level, name)


def set_eval_goal(level, name: str | None) -> str:
    return set_eval_goal_checked(level, name)


def resolve_run_goal(
    settings: RunSettings,
    *,
    eval_goal_name: str | None = None,
) -> str:
    return normalize_eval_goal(eval_goal_name or settings.eval_goal)


def _resolve_bot_eval_goals(bot) -> tuple[str, ...]:
    getter = getattr(bot, "supported_eval_goals", None)
    if not callable(getter):
        return (EVAL_GOAL_LANDING,)
    raw_goals = getter()
    if raw_goals is not None and not isinstance(
        raw_goals, (list, tuple, set, frozenset)
    ):
        raise ValueError(
            f"Bot '{type(bot).__name__}' returned invalid supported_eval_goals()"
        )
    return normalize_eval_goals(cast(Iterable[str] | None, raw_goals))


def _load_bot_config(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ValueError(f"Bot config file not found: {config_path}")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid bot config JSON at {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Bot config must be a JSON object: {config_path}")
    return dict(payload)


def configure_level(
    level, settings: RunSettings, *, benchmark_mode: str | None = None
) -> None:
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

    set_benchmark_mode_checked(level, benchmark_mode)

    level.set_trace_config(
        enabled=settings.trace_enabled,
        sample_period_s=settings.trace_sample_period_s,
        detail=settings.trace_detail,
        root_dir=settings.trace_root_dir,
    )
    level.max_time = settings.max_time
    if settings.lander_name:
        setattr(level, "lander_name", settings.lander_name)


def run_once(
    settings: RunSettings,
    *,
    seed: int | None = None,
    level_name: str | None = None,
    eval_scenario_name: str | None = None,
    eval_goal_name: str | None = None,
    display_level_name: str | None = None,
    display_scenario_name: str | None = None,
    print_results: bool = True,
    benchmark_mode: str | None = None,
    trace_selector_tag: str | None = None,
    run_key: str | None = None,
    run_instance_id: int | None = None,
) -> dict[str, Any]:
    runtime_level_name = level_name or settings.runtime_level_name
    public_level_name = display_level_name or settings.level_name
    public_scenario_name = (
        display_scenario_name
        if display_scenario_name is not None
        else settings.scenario_name
    )

    level = create_level_checked(runtime_level_name)
    level.set_runtime_identity(
        level_name=public_level_name,
        public_scenario_name=public_scenario_name or public_level_name,
    )

    chosen_scenario = (
        eval_scenario_name
        if eval_scenario_name is not None
        else settings.runtime_scenario_name
    )
    set_eval_scenario(level, chosen_scenario)
    run_goal = resolve_run_goal(settings, eval_goal_name=eval_goal_name)
    run_goal = set_eval_goal(level, run_goal)
    configure_level(level, settings, benchmark_mode=benchmark_mode)
    if trace_selector_tag:
        level.set_runtime_identity(trace_selector_tag=str(trace_selector_tag))

    run_bot_name = resolve_run_bot_name(settings, level)
    bot_config = _load_bot_config(settings.bot_config_path)
    bot = (
        _create_bot(run_bot_name, config_override=bot_config)
        if run_bot_name is not None
        else None
    )
    if bot is not None and run_bot_name is not None:
        supported_goals = _resolve_bot_eval_goals(bot)
        if run_goal not in supported_goals:
            supported_csv = ", ".join(supported_goals)
            raise ValueError(
                f"Bot '{run_bot_name}' does not support eval goal '{run_goal}'. "
                f"Supported goals: {supported_csv}"
            )
        bot.set_eval_goal(run_goal)
        bot.set_identity_name(run_bot_name)
    if run_goal != EVAL_GOAL_LANDING and bot is None:
        raise ValueError(
            f"Eval goal '{run_goal}' requires a bot. "
            "Provide --bot or choose the default landing goal."
        )

    game = LanderGame(
        seed=seed,
        bot=bot,
        headless=settings.headless,
        level=level,
        eval_goal=run_goal,
        bot_profile_enabled=settings.bot_profile_enabled,
        bot_profile_interval_s=settings.bot_profile_interval_s,
        bot_profile_log_lines=settings.bot_profile_log_lines,
        runtime_adapter=make_runtime_adapter(bot, settings.headless),
    )
    result = game.run(
        print_freq=settings.print_freq,
        max_time=settings.max_time,
        max_steps=settings.max_steps,
    )

    if run_bot_name is not None:
        result["_bot_name"] = run_bot_name
    result["_level_name"] = public_level_name
    result["_scenario_name"] = public_scenario_name or public_level_name
    result["_eval_goal"] = run_goal
    if run_key is not None:
        result["run_key"] = str(run_key)
    if run_instance_id is not None:
        result["run_instance_id"] = int(run_instance_id)

    if settings.headless and print_results:
        print_headless_results(result)
    return result


def run_once_record(
    settings: RunSettings,
    *,
    seed: int | None,
    level_name: str,
    eval_scenario_name: str | None = None,
    eval_goal_name: str | None = None,
    record_level_name: str | None = None,
    record_scenario_name: str | None = None,
    benchmark_mode: str | None = None,
    trace_selector_tag: str | None = None,
    run_key: str | None = None,
    run_instance_id: int | None = None,
) -> dict[str, Any]:
    result = run_once(
        settings,
        seed=seed,
        level_name=level_name,
        eval_scenario_name=eval_scenario_name,
        eval_goal_name=eval_goal_name,
        display_level_name=record_level_name,
        display_scenario_name=record_scenario_name,
        print_results=False,
        benchmark_mode=benchmark_mode,
        trace_selector_tag=trace_selector_tag,
        run_key=run_key,
        run_instance_id=run_instance_id,
    )
    record_bot_name = str(result.get("_bot_name") or settings.bot_name or "none")
    record_level_name = str(
        result.get("_level_name") or record_level_name or settings.level_name
    )
    record_scenario_name = str(
        result.get("_scenario_name") or record_scenario_name or record_level_name
    )
    return normalize_run_result(
        bot_name=record_bot_name,
        level_name=record_level_name,
        scenario=record_scenario_name,
        seed=seed,
        result=result,
    )
