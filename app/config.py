from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchTarget:
    level_name: str
    scenario_name: str | None
    seed_spec: str | None


@dataclass(frozen=True)
class RunSettings:
    level_name: str
    bot_name: str | None
    seed: int | None
    scenario_name: str | None
    lander_name: str | None
    eval_mode: str
    print_freq: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    stop_on_crash: bool
    stop_on_out_of_fuel: bool
    stop_on_first_land: bool
    headless: bool
    bot_profile_enabled: bool | None = None
    bot_profile_interval_s: float | None = None
    bot_profile_log_lines: bool | None = None


@dataclass(frozen=True)
class BenchSettings:
    bot_name: str | None
    selectors: tuple[BenchTarget, ...]
    lander_name: str | None
    eval_mode: str
    workers: int
    max_time: float
    max_steps: int | None
    plot_mode: str
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
