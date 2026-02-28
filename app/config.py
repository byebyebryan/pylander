from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class BenchSettings:
    bot_name: str | None
    level_name: str
    level_names_csv: str | None
    seeds_csv: str | None
    scenarios_csv: str | None
    scenario_name: str | None
    lander_name: str | None
    eval_mode: str
    quick: bool
    workers: int
    max_time: float
    max_steps: int | None
    plot_mode: str
    json_path: str | None
    csv_path: str | None


@dataclass(frozen=True)
class PlayCommand:
    run: RunSettings


@dataclass(frozen=True)
class RunCommand:
    run: RunSettings


@dataclass(frozen=True)
class BenchCommand:
    bench: BenchSettings


Command = PlayCommand | RunCommand | BenchCommand
