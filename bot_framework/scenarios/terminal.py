from __future__ import annotations

from game.core.level import Level
from game.core.maths import Vector2
from bot_framework.scenarios._catalog_mixin import ScenarioCatalogMixin
from game.shared.common_scenarios import (
    ScenarioLevel,
    make_flat_scenario_spec,
)
from bot_framework.scenarios.terminal_catalog import (
    TERMINAL_DEFAULT_SCENARIO,
    TERMINAL_QUICK_SCENARIOS,
    TERMINAL_SCENARIO_BY_NAME,
    TERMINAL_SMOKE_SCENARIOS,
    TerminalScenario,
)
from bot_framework.scenarios.terminal_spawn import (
    apply_terminal_spawn,
    resolve_terminal_error_spawn,
    sample_terminal_normal_candidate,
    select_terminal_normal_spawn,
    terminal_scenario_has_randomized_fields,
    validate_terminal_error_recoverability,
)


class TerminalLevel(ScenarioCatalogMixin[TerminalScenario], ScenarioLevel):
    _scenario_by_name = TERMINAL_SCENARIO_BY_NAME
    _default_scenario_name = TERMINAL_DEFAULT_SCENARIO
    _smoke_benchmark_scenarios = TERMINAL_SMOKE_SCENARIOS
    _quick_benchmark_scenarios = TERMINAL_QUICK_SCENARIOS

    def __init__(self) -> None:
        super().__init__()
        self._init_scenario_catalog()
        scenario = self._active_scenario()
        self.scenario = make_flat_scenario_spec(
            name=scenario.name,
            start_dx=0.0,
            start_dy=800.0,
            cargo_mass=float(scenario.cargo_mass),
        )

    def scenario_has_randomized_fields(self, _name: str | None = None) -> bool:
        return terminal_scenario_has_randomized_fields(self._active_scenario())

    def setup(self, game, seed: int) -> None:
        scenario = self._active_scenario()
        if scenario.mode == "normal":
            pre_candidate = sample_terminal_normal_candidate(
                scenario=scenario,
                seed=seed,
                attempt=0,
                target_pos=Vector2(0.0, 0.0),
                benchmark_random_mode=self._benchmark_random_mode,
            )
            self.scenario = make_flat_scenario_spec(
                name=scenario.name,
                start_dx=pre_candidate.start_dx,
                start_dy=max(0.0, pre_candidate.start_dy),
                cargo_mass=float(scenario.cargo_mass),
            )
        else:
            self.scenario = make_flat_scenario_spec(
                name=scenario.name,
                start_dx=0.0,
                start_dy=800.0,
                cargo_mass=float(scenario.cargo_mass),
            )
        super().setup(game, seed)
        if self.world is None:
            raise RuntimeError("TerminalLevel world was not initialized")

        actor = self.world.actors[0]
        target_pos = self.eval_target_pos or Vector2(0.0, 0.0)
        engine = self.engine

        if scenario.mode == "normal":
            candidate, margin_t, margin_h, downspeed = select_terminal_normal_spawn(
                actor=actor,
                scenario=scenario,
                seed=seed,
                benchmark_random_mode=self._benchmark_random_mode,
                target_pos=target_pos,
            )
            apply_terminal_spawn(actor, engine, candidate, retrograde=True)
            self._set_scenario_params(
                {
                    "mode": scenario.mode,
                    "profile": scenario.profile,
                    "radius": candidate.radius,
                    "entry_angle_deg": candidate.entry_angle_deg,
                    "angle_deviation_deg": candidate.angle_deviation_deg,
                    "target_flight_time_s": candidate.target_flight_time_s,
                    "direction": candidate.direction,
                    "trim_time_s": candidate.trim_time_s,
                    "tgo_start_s": candidate.t_go_start_s,
                    "focus_margin_m": candidate.focus_margin_m,
                    "validity_margin_time_s": margin_t,
                    "validity_margin_altitude_m": margin_h,
                    "validity_downspeed_mps": downspeed,
                }
            )
        else:
            candidate, params = resolve_terminal_error_spawn(
                scenario=scenario,
                seed=seed,
                benchmark_random_mode=self._benchmark_random_mode,
                target_pos=target_pos,
            )
            validate_terminal_error_recoverability(actor, scenario, candidate)
            apply_terminal_spawn(actor, engine, candidate, retrograde=False)
            self._set_scenario_params(
                {
                    "mode": scenario.mode,
                    "profile": scenario.profile,
                    "error_tier": scenario.error_tier or "",
                    **params,
                }
            )
        self.set_runtime_identity(scenario_name=scenario.name)

    def update(self, game, dt: float) -> None:
        _ = game, dt

    def end(self, game):
        return super().end(game)


def create_level() -> Level:
    return TerminalLevel()
