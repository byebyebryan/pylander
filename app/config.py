from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchTarget:
    level_name: str
    scenario_name: str | None
    seed_spec: str | None
    scenario_path: tuple[str, ...] = ()
    eval_goal: str = "landing"


@dataclass(frozen=True)
class RunSettings:
    level_name: str
    runtime_level_name: str
    bot_name: str | None
    bot_config_path: str | None
    seed: int | None
    scenario_name: str | None
    runtime_scenario_name: str | None
    lander_name: str | None
    print_freq: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    plot_output: str
    plot_max_side_px: int
    stop_on_crash: bool
    stop_on_out_of_fuel: bool
    stop_on_first_land: bool
    headless: bool
    eval_goal: str = "landing"
    bot_profile_enabled: bool | None = None
    bot_profile_interval_s: float | None = None
    bot_profile_log_lines: bool | None = None


@dataclass(frozen=True)
class BenchSettings:
    bot_name: str | None
    bot_config_path: str | None
    selectors: tuple[BenchTarget, ...]
    lander_name: str | None
    workers: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    plot_output: str
    plot_max_side_px: int
    json_path: str | None
    csv_path: str | None
    bot_profile_enabled: bool = True
    bot_profile_interval_s: float | None = None
    bot_profile_log_lines: bool = False


@dataclass(frozen=True)
class RunCommand:
    run: RunSettings


@dataclass(frozen=True)
class BenchCommand:
    bench: BenchSettings


Command = RunCommand | BenchCommand
