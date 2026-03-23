from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import app.run_batch as run_batch_module
import app.run_single as run_single_module
from app.cli import build_parser, parse_command
from app.config import BenchCommand, BenchSettings, BenchTarget, RunCommand
from bots import create_bot, list_available_bots
from core.bot import Bot, BotAction, BotDisplayState, Sensors, resolve_bot_display_state
from core.components import CargoHold, LandingSite, PhysicsState, Transform
from core.ecs import require_component
from core.eval import aggregate_eval_records, normalize_run_result
from game import LanderGame
from levels import create_level as create_level_by_name, list_available_levels
from app.run_batch import ResolvedBenchRun, parse_seed_spec, resolve_benchmark_plan


def test_bot_registry_exposes_only_supported_bots() -> None:
    bots = list_available_bots()
    assert "plunge" in bots
    assert "pdg" in bots
    assert "coast" not in bots
    assert "terminal" not in bots
    assert "boost" not in bots
    assert "launch" not in bots

    plunge_bot = create_bot("plunge")
    pdg_bot = create_bot("pdg")
    assert plunge_bot.__class__.__name__ == "PlungeBot"
    assert pdg_bot.__class__.__name__ == "PDGBot"
    assert isinstance(plunge_bot, Bot)
    assert isinstance(pdg_bot, Bot)


def test_create_bot_rejects_config_override_for_unsupported_bot() -> None:
    with pytest.raises(ValueError, match="does not support --bot-config"):
        create_bot("plunge", config_override={"boost_cutoff_projected_dx_abs": 42.0})


def test_create_bot_applies_pdg_bot_config_override() -> None:
    bot = create_bot(
        "pdg",
        config_override={
            "boost_cutoff_projected_dx_abs": 42.0,
            "fallback_hold_steps": 10.0,
        },
    )
    cfg = getattr(bot, "_cfg")
    assert float(cfg.boost_cutoff_projected_dx_abs) == pytest.approx(42.0)
    assert int(cfg.fallback_hold_steps) == 10


def test_level_registry_still_includes_phase_levels() -> None:
    levels = list_available_levels()
    assert "flare_plunge" not in levels
    for name in ("flat", "mountains", "boost", "terminal", "plunge"):
        assert name in levels
    for removed in (
        "terminal_normal",
        "terminal_error",
        "boost_downhill",
        "boost_flat",
        "boost_climb",
    ):
        assert removed not in levels


def test_terminal_level_scenario_names_are_canonical() -> None:
    level = create_level_by_name("terminal")
    assert level.list_batch_scenarios() == [
        "normal:shallower",
        "normal:shallow",
        "normal:mid",
        "normal:steep",
        "normal:steeper",
        "error:shallower:tight",
        "error:shallower:wide",
        "error:shallow:tight",
        "error:shallow:wide",
        "error:mid:tight",
        "error:mid:wide",
        "error:steep:tight",
        "error:steep:wide",
        "error:steeper:tight",
        "error:steeper:wide",
    ]
    assert level.list_quick_benchmark_scenarios() == [
        "normal:shallow",
        "normal:mid",
        "normal:steep",
        "error:shallow:tight",
        "error:mid:wide",
        "error:steep:wide",
    ]


def test_boost_level_scenario_names_are_canonical() -> None:
    level = create_level_by_name("boost")
    assert level.list_batch_scenarios() == [
        "flat:near:empty",
        "flat:near:half",
        "flat:near:full",
        "flat:mid:empty",
        "flat:mid:half",
        "flat:mid:full",
        "flat:far:empty",
        "flat:far:half",
        "flat:far:full",
        "downhill:low:empty",
        "downhill:low:half",
        "downhill:low:full",
        "downhill:mid:empty",
        "downhill:mid:half",
        "downhill:mid:full",
        "downhill:high:empty",
        "downhill:high:half",
        "downhill:high:full",
        "climb:low:empty",
        "climb:low:half",
        "climb:low:full",
        "climb:mid:empty",
        "climb:mid:half",
        "climb:mid:full",
        "climb:high:empty",
        "climb:high:half",
        "climb:high:full",
    ]
    assert level.list_quick_benchmark_scenarios() == [
        "flat:mid:half",
        "downhill:low:half",
        "downhill:mid:half",
        "downhill:high:half",
        "climb:low:half",
        "climb:mid:half",
        "climb:high:half",
    ]


def test_boost_rejects_unknown_scenario() -> None:
    level = create_level_by_name("boost")
    with pytest.raises(ValueError, match="Unknown boost scenario"):
        level.set_eval_scenario("bad")


@pytest.mark.parametrize(
    ("level_name", "legacy_scenario"),
    (
        ("boost", "mid"),
        ("terminal", "mid"),
    ),
)
def test_setup_levels_reject_legacy_bare_scenarios(
    level_name: str, legacy_scenario: str
) -> None:
    level = create_level_by_name(level_name)
    with pytest.raises(ValueError, match="Unknown"):
        level.set_eval_scenario(legacy_scenario)


def test_boost_defaults_to_flat_mid_half() -> None:
    level_name = "boost"
    level = create_level_by_name(level_name)
    game = LanderGame(level=level, seed=0, bot=create_bot("pdg"), headless=True)
    assert game.level.scenario_name == "flat:mid:half"


def test_boost_climb_target_is_terrain_bound_flush_pad() -> None:
    level = create_level_by_name("boost")
    level.set_eval_scenario("climb:mid:half")
    game = LanderGame(level=level, seed=0, bot=create_bot("pdg"), headless=True)
    target = next(
        site
        for site in game.level.world.site_entities
        if site.uid == "transfer_target"
    )
    shape = target.get_component(LandingSite)
    assert shape is not None
    assert shape.terrain_mode == "flush_flatten"
    assert shape.terrain_bound is True


@pytest.mark.parametrize(
    "scenario_name",
    ["climb:mid:half", "flat:mid:half", "downhill:mid:half"],
)
def test_landed_site_uid_requires_pad_overlap(scenario_name: str) -> None:
    level = create_level_by_name("boost")
    level.set_eval_scenario(scenario_name)
    _game = LanderGame(level=level, seed=0, bot=create_bot("pdg"), headless=True)
    target = next(
        spec for spec in level.site_specs if spec.uid == "transfer_target"
    )
    half = 0.5 * float(target.size)
    assert level._resolve_landed_site_uid(float(target.x)) == "transfer_target"
    assert level._resolve_landed_site_uid(float(target.x) + half + 2.0) is None


def _spawn_state(
    level_name: str, scenario: str, seed: int
) -> tuple[float, float, float, float, float]:
    level = create_level_by_name(level_name)
    level.set_eval_scenario(scenario)
    game = LanderGame(level=level, seed=seed, bot=create_bot("pdg"), headless=True)
    actor = game.level.world.actors[0]
    trans = require_component(actor, Transform)
    phys = require_component(actor, PhysicsState)
    return (
        float(trans.pos.x),
        float(trans.pos.y),
        float(phys.vel.x),
        float(phys.vel.y),
        float(trans.rotation),
    )


def test_setup_and_terminal_error_scenarios_are_seed_deterministic() -> None:
    setup_a = _spawn_state("boost", "downhill:mid:half", 42)
    setup_b = _spawn_state("boost", "downhill:mid:half", 42)
    assert setup_a == pytest.approx(setup_b)

    coast_a = _spawn_state("terminal", "error:mid:tight", 42)
    coast_b = _spawn_state("terminal", "error:mid:tight", 42)
    assert coast_a == pytest.approx(coast_b)

    climb_a = _spawn_state("boost", "climb:mid:half", 42)
    climb_b = _spawn_state("boost", "climb:mid:half", 42)
    assert climb_a == pytest.approx(climb_b)


@pytest.mark.parametrize(
    ("level_name", "scenario_name", "expected_cargo_mass", "expected_cargo_fraction"),
    (
        ("boost", "flat:near:empty", 0.0, 0.0),
        ("boost", "flat:near:half", 3000.0, 0.5),
        ("boost", "flat:near:full", 6000.0, 1.0),
        ("boost", "downhill:mid:half", 3000.0, 0.5),
        ("boost", "climb:high:full", 6000.0, 1.0),
    ),
)
def test_setup_levels_apply_weight_tier_mass_and_params(
    level_name: str,
    scenario_name: str,
    expected_cargo_mass: float,
    expected_cargo_fraction: float,
) -> None:
    level = create_level_by_name(level_name)
    level.set_eval_scenario(scenario_name)
    game = LanderGame(level=level, seed=7, bot=create_bot("pdg"), headless=True)

    actor = game.level.world.actors[0]
    cargo = require_component(actor, CargoHold)
    assert cargo.effective_mass == pytest.approx(expected_cargo_mass)
    assert level._scenario_params["weight_tier"] == scenario_name.rsplit(":", 1)[-1]
    assert level._scenario_params["cargo_mass"] == pytest.approx(expected_cargo_mass)
    assert level._scenario_params["cargo_fraction"] == pytest.approx(
        expected_cargo_fraction
    )


def test_boost_flat_weight_tiers_share_same_sampled_route_for_same_seed() -> None:
    target_x_by_weight: dict[str, float] = {}
    for scenario_name in ("flat:far:empty", "flat:far:half", "flat:far:full"):
        level = create_level_by_name("boost")
        level.set_eval_scenario(scenario_name)
        _game = LanderGame(level=level, seed=19, bot=create_bot("pdg"), headless=True)
        target_site = next(
            spec for spec in level.site_specs if spec.uid == "transfer_target"
        )
        target_x_by_weight[scenario_name] = float(target_site.x)

    assert target_x_by_weight["flat:far:empty"] == pytest.approx(
        target_x_by_weight["flat:far:half"]
    )
    assert target_x_by_weight["flat:far:half"] == pytest.approx(
        target_x_by_weight["flat:far:full"]
    )


def test_pdg_boost_goal_ends_headless_run_early() -> None:
    level = create_level_by_name("boost")
    level.set_eval_scenario("downhill:mid:half")
    bot = create_bot("pdg")
    bot.set_eval_goal("boost_cutoff")
    game = LanderGame(level=level, seed=0, bot=bot, headless=True, eval_goal="boost_cutoff")

    result = game.run(print_freq=0, max_time=120.0)
    assert result["eval_goal"] == "boost_cutoff"
    assert result["eval_early_end"] is True
    assert result["boost_cutoff_done"] is True
    assert result["boost_goal_done"] is True
    assert result["boost_goal_has_target_y_solution"] is True
    assert result["boost_goal_projected_impact_angle_deg"] is not None
    if result["success"]:
        assert result["failure_mode"] == "none"
        assert result["boost_quality_verdict"] == "pass"
    else:
        assert result["failure_mode"] == "boost_quality_failed"
        assert result["boost_quality_verdict"] in {
            "dx",
            "angle",
            "no_target_y_solution",
        }


def test_non_landing_goal_without_decision_fails_goal_not_reached() -> None:
    class _NoGoalBot(Bot):
        def set_eval_goal(self, goal: str) -> None:
            key = str(goal or "landing").strip().lower()
            if key not in {"landing", "boost_cutoff"}:
                raise ValueError("unsupported goal")
            self._eval_goal = key

        def update(self, dt: float, sensors: Sensors) -> BotAction:
            _ = dt, sensors
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    bot = _NoGoalBot()
    bot.set_eval_goal("boost_cutoff")
    game = LanderGame(
        level=create_level_by_name("flat"),
        seed=0,
        bot=bot,
        headless=True,
        eval_goal="boost_cutoff",
    )
    result = game.run(print_freq=0, max_steps=5, max_time=5.0)

    assert result["eval_goal"] == "boost_cutoff"
    assert result["eval_early_end"] is False
    assert result["success"] is False
    assert result["failure_mode"] == "goal_not_reached"


def test_normalize_run_result_uses_canonical_eval_fields() -> None:
    record = normalize_run_result(
        bot_name="pdg",
        level_name="boost",
        scenario="downhill:mid:half",
        seed=3,
        result={
            "state": "flying",
            "success": True,
            "eval_goal": "boost_cutoff",
            "eval_early_end": True,
            "eval_end_reason": "goal_reached",
            "boost_goal_done": True,
            "boost_goal_time": 6.0,
            "boost_goal_altitude": 120.0,
            "boost_goal_projected_apex_y": 180.0,
            "boost_goal_projected_apex_over_target": 60.0,
            "boost_goal_has_target_y_solution": True,
            "boost_goal_projected_dx": 8.0,
            "boost_goal_projected_impact_angle_deg": 57.0,
            "boost_goal_burn_avg_thrust_level": 0.84,
            "boost_cutoff_done": True,
            "boost_cutoff_time": 6.0,
            "boost_cutoff_altitude": 120.0,
            "boost_cutoff_projected_apex_y": 180.0,
            "boost_cutoff_projected_apex_over_target": 60.0,
            "boost_cutoff_has_target_y_solution": True,
            "boost_cutoff_projected_dx": 8.0,
            "boost_cutoff_projected_impact_angle_deg": 57.0,
            "boost_cutoff_burn_duration_s": 6.0,
            "boost_cutoff_burn_fuel_used": 17.0,
            "boost_cutoff_burn_avg_thrust_level": 0.84,
            "transfer_arrived": False,
            "bot_pdg_terminal_entry_done": True,
            "bot_pdg_terminal_entry_time": 8.6,
            "bot_pdg_terminal_entry_altitude": 72.0,
            "bot_pdg_terminal_entry_projected_dx": 4.5,
            "bot_pdg_solve_count": 32,
            "bot_pdg_solve_ms_mean": 3.2,
            "bot_pdg_solve_ms_p90": 7.4,
            "bot_pdg_fallback_frames": 1,
            "bot_pdg_shape_apex_error": 4.0,
            "bot_pdg_shape_curve_rmse": 14.5,
            "bot_pdg_shape_projected_dx_abs_mean": 18.0,
            "bot_pdg_shape_projected_dx_abs_max": 41.0,
            "bot_pdg_shape_shortfall_ratio": 0.12,
        },
    )
    assert record["success"] is True
    assert record["eval_goal"] == "boost_cutoff"
    assert record["eval_early_end"] is True
    assert record["eval_end_reason"] == "goal_reached"
    assert record["boost_goal_done"] is True
    assert record["boost_goal_time"] == pytest.approx(6.0)
    assert record["boost_goal_altitude"] == pytest.approx(120.0)
    assert record["boost_goal_projected_apex_over_target"] == pytest.approx(60.0)
    assert record["boost_goal_has_target_y_solution"] is True
    assert record["boost_goal_projected_dx"] == pytest.approx(8.0)
    assert record["boost_goal_projected_impact_angle_deg"] == pytest.approx(57.0)
    assert record["boost_cutoff_done"] is True
    assert record["boost_cutoff_burn_duration_s"] == pytest.approx(6.0)
    assert record["boost_cutoff_burn_fuel_used"] == pytest.approx(17.0)
    assert record["transfer_arrived"] is False
    assert record["bot_pdg_terminal_entry_done"] is True
    assert record["bot_pdg_terminal_entry_time"] == pytest.approx(8.6)
    assert record["bot_pdg_terminal_entry_altitude"] == pytest.approx(72.0)
    assert record["bot_pdg_terminal_entry_projected_dx"] == pytest.approx(4.5)
    assert record["bot_pdg_solve_count"] == pytest.approx(32.0)
    assert record["bot_pdg_solve_ms_mean"] == pytest.approx(3.2)
    assert record["bot_pdg_solve_ms_p90"] == pytest.approx(7.4)
    assert record["bot_pdg_fallback_frames"] == pytest.approx(1.0)
    assert record["bot_pdg_shape_apex_error"] == pytest.approx(4.0)
    assert record["bot_pdg_shape_curve_rmse"] == pytest.approx(14.5)
    assert record["bot_pdg_shape_projected_dx_abs_mean"] == pytest.approx(18.0)
    assert record["bot_pdg_shape_projected_dx_abs_max"] == pytest.approx(41.0)
    assert record["bot_pdg_shape_shortfall_ratio"] == pytest.approx(0.12)


def test_boost_flat_run_merges_bot_telemetry_fields_into_result() -> None:
    level = create_level_by_name("boost")
    level.set_eval_scenario("flat:near:half")
    game = LanderGame(level=level, seed=0, bot=create_bot("pdg"), headless=True)
    result = game.run(print_freq=0, max_steps=2, max_time=2.0)
    assert result["scenario_weight_tier"] == "half"
    assert result["scenario_cargo_mass"] == pytest.approx(3000.0)
    assert result["scenario_cargo_fraction"] == pytest.approx(0.5)
    assert "bot_pdg_solve_count" in result
    assert "bot_pdg_shape_curve_rmse" in result


def test_eval_aggregate_uses_explicit_success_for_staged_records() -> None:
    records = [
        normalize_run_result(
            bot_name="pdg",
            level_name="boost",
            scenario="downhill:mid:half",
            seed=0,
            result={
                "state": "flying",
                "success": True,
                "eval_goal": "boost_cutoff",
                "eval_early_end": True,
                "boost_goal_done": True,
                "boost_goal_time": 6.0,
            },
        )
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 1
    assert summary["successes"] == 1
    assert summary["success_rate"] == pytest.approx(1.0)
    assert summary["by_scenario"]["downhill:mid:half"]["success_rate"] == pytest.approx(1.0)
    assert summary["by_selector"]["boost:downhill:mid:half:boost_cutoff"][
        "success_rate"
    ] == pytest.approx(1.0)


def test_parse_seed_spec_keeps_order_and_deduplicates() -> None:
    assert parse_seed_spec("0-2,2,5,4-3") == [0, 1, 2, 5, 4, 3]


def test_resolve_default_bot_invalid_level_fails_fast() -> None:
    with pytest.raises(ValueError, match="Failed to load level 'missing_level'"):
        run_single_module.resolve_default_bot("missing_level")


def test_resolve_benchmark_plan_invalid_level_fails_fast() -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(
            BenchTarget(level_name="missing_level", scenario_name=None, seed_spec=None),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=None,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=None,
    )

    with pytest.raises(ValueError, match="Unknown level 'missing_level'"):
        resolve_benchmark_plan(config)


def test_parser_rejects_removed_bot_behavior_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "plunge", "--bot-behavior", "balanced"])


def test_resolve_batch_plan_expands_explicit_wildcards_without_seed_spec(
    monkeypatch,
) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="plunge",
                scenario_name="*",
                scenario_path=("*",),
                seed_spec=None,
            ),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=None,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=None,
    )
    monkeypatch.setattr(
        run_batch_module, "_scenario_has_randomized_fields", lambda _l, _s: False
    )
    plan = resolve_benchmark_plan(config)
    assert plan == [
        ResolvedBenchRun(
            0,
            "plunge",
            "low:half",
            "plunge",
            "low:half",
            "landing",
            run_key="plunge:low:half:0",
        ),
        ResolvedBenchRun(
            0,
            "plunge",
            "mid:half",
            "plunge",
            "mid:half",
            "landing",
            run_key="plunge:mid:half:0",
        ),
        ResolvedBenchRun(
            0,
            "plunge",
            "high:half",
            "plunge",
            "high:half",
            "landing",
            run_key="plunge:high:half:0",
        ),
    ]


def test_resolve_batch_plan_honors_selector_seed_spec(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="boost",
                scenario_name="flat:far:half",
                scenario_path=("flat", "far", "half"),
                seed_spec="0-2,2",
            ),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=None,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=None,
    )
    monkeypatch.setattr(
        run_batch_module, "_scenario_has_randomized_fields", lambda _l, _s: False
    )
    plan = resolve_benchmark_plan(config)
    assert plan == [
        ResolvedBenchRun(
            0,
            "boost",
            "flat:far:half",
            "boost",
            "flat:far:half",
            "landing",
            run_key="boost:flat:far:half:0",
        ),
        ResolvedBenchRun(
            1,
            "boost",
            "flat:far:half",
            "boost",
            "flat:far:half",
            "landing",
            run_key="boost:flat:far:half:1",
        ),
        ResolvedBenchRun(
            2,
            "boost",
            "flat:far:half",
            "boost",
            "flat:far:half",
            "landing",
            run_key="boost:flat:far:half:2",
        ),
    ]


def test_resolve_batch_plan_assigns_unique_run_keys_for_duplicate_selectors(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="plunge",
                scenario_name="low:half",
                scenario_path=("low", "half"),
                seed_spec="0",
            ),
            BenchTarget(
                level_name="plunge",
                scenario_name="low:half",
                scenario_path=("low", "half"),
                seed_spec="0",
            ),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=None,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=None,
    )
    monkeypatch.setattr(
        run_batch_module, "_scenario_has_randomized_fields", lambda _l, _s: False
    )

    plan = resolve_benchmark_plan(config)

    assert [target.run_key for target in plan] == [
        "plunge:low:half:0#1",
        "plunge:low:half:0#2",
    ]
    assert [target.run_instance_id for target in plan] == [1, 2]


def test_hud_display_state_returns_none_when_display_state_is_missing() -> None:
    class _Bot:
        pass

    assert resolve_bot_display_state(_Bot()) is None


def test_hud_display_state_prefers_structured_display_state() -> None:
    class _Bot:
        def get_display_state(self):
            return BotDisplayState(
                bot_name="pdg",
                mode="opt",
                phase="boost",
                summary="dx=12.3 pdx=-4.0",
            )

    display = resolve_bot_display_state(_Bot())
    assert display is not None
    assert display.bot_name == "pdg"
    assert display.phase == "boost"


def test_parse_args_accepts_level_goal_selector() -> None:
    _parser, command = parse_command(
        ["sim", "boost:downhill:mid:half:boost_cutoff:0", "--bot", "pdg"]
    )
    assert isinstance(command, RunCommand)
    assert command.run.bot_name == "pdg"
    assert command.run.level_name == "boost"
    assert command.run.scenario_name == "downhill:mid:half"
    assert command.run.runtime_level_name == "boost"
    assert command.run.runtime_scenario_name == "downhill:mid:half"
    assert command.run.eval_goal == "boost_cutoff"


def test_cli_requires_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parse_play_command_uses_interactive_defaults() -> None:
    _parser, command = parse_command(["play"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "flat"
    assert command.run.headless is False
    assert command.run.trace_enabled is False
    assert command.run.trace_sample_period_s == 0.25


def test_parse_play_command_accepts_selector_and_bot() -> None:
    _parser, command = parse_command(["play", "boost:flat:far:half:3", "--bot", "pdg"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "boost"
    assert command.run.scenario_name == "flat:far:half"
    assert command.run.runtime_level_name == "boost"
    assert command.run.runtime_scenario_name == "flat:far:half"
    assert command.run.seed == 3
    assert command.run.bot_name == "pdg"
    assert command.run.headless is False


def test_parse_bench_command_uses_expected_defaults() -> None:
    _parser, command = parse_command(["bench", "plunge"])
    assert isinstance(command, BenchCommand)
    assert command.bench.selectors == (
        BenchTarget(level_name="plunge", scenario_name=None, seed_spec=None, scenario_path=()),
    )
    assert command.bench.workers == max(1, int(os.cpu_count() or 1) - 2)
    assert command.bench.trace_enabled is True
    assert command.bench.trace_sample_period_s == 0.25
    assert command.bench.json_path == "auto"
    assert command.bench.bot_profile_enabled is True
    assert command.bench.bot_profile_log_lines is False
    assert command.bench.bot_profile_interval_s is None


def test_parse_bench_command_rejects_workers_override() -> None:
    with pytest.raises(SystemExit):
        parse_command(["bench", "plunge", "--workers", "1"])


def test_parse_bench_command_rejects_removed_csv_flag() -> None:
    with pytest.raises(SystemExit):
        parse_command(["bench", "plunge", "--csv", "auto"])


def test_parse_bench_command_profile_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "bench",
            "plunge",
            "--no-bot-profile",
            "--bot-profile-logs",
            "--bot-profile-interval-s",
            "1.5",
        ]
    )
    assert isinstance(command, BenchCommand)
    assert command.bench.bot_profile_enabled is False
    assert command.bench.bot_profile_log_lines is True
    assert command.bench.bot_profile_interval_s == 1.5


def test_parse_bench_command_trace_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "bench",
            "plunge",
            "--trace-sample-period-s",
            "0.5",
        ]
    )
    assert isinstance(command, BenchCommand)
    assert command.bench.trace_enabled is True
    assert command.bench.trace_sample_period_s == 0.5


def test_parse_plot_command_trace_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "plot",
            "boost:flat:far:half:3",
            "--bot",
            "pdg",
            "--trace-sample-period-s",
            "0.1",
        ]
    )
    assert isinstance(command, RunCommand)
    assert command.run.trace_enabled is True
    assert command.run.trace_sample_period_s == 0.1


def test_run_benchmark_parallel_run_failure_is_not_reclassified(monkeypatch) -> None:
    class _FailFuture:
        def result(self):
            raise ValueError("boom")

    class _FakePool:
        def __init__(self, *, max_workers: int):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, _fn, *_args, **_kwargs):
            return _FailFuture()

    monkeypatch.setattr(run_batch_module, "ProcessPoolExecutor", _FakePool)
    monkeypatch.setattr(run_batch_module, "as_completed", lambda futures: list(futures))
    monkeypatch.setattr(
        run_batch_module,
        "resolve_benchmark_plan",
        lambda _cfg: [
            ResolvedBenchRun(0, "boost", "flat:mid:half", "boost", "flat:mid:half", "landing"),
            ResolvedBenchRun(1, "boost", "flat:mid:half", "boost", "flat:mid:half", "landing"),
        ],
    )

    cfg = BenchSettings(
        bot_name="pdg",
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="boost",
                scenario_name="flat:mid:half",
                scenario_path=("flat", "mid", "half"),
                seed_spec="0",
            ),
        ),
        lander_name=None,
        workers=4,
        max_time=300.0,
        max_steps=None,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=None,
    )
    with pytest.raises(
        RuntimeError,
        match="run 1/2 seed=0 level=boost scenario=flat:mid:half failed",
    ):
        run_batch_module.run_benchmark(cfg)


def test_resolve_output_path_keeps_explicit_path_even_when_file_exists(tmp_path) -> None:
    explicit = tmp_path / "report.tracepack.json"
    explicit.write_text("old", encoding="utf-8")

    resolved = run_batch_module._resolve_output_path(
        str(explicit),
        kind="tracepack.json",
        level_name="boost",
        bot_name="pdg",
        seeds=[0],
        scenarios=["boost:flat:mid:half"],
    )

    assert resolved == explicit


def test_run_benchmark_writes_absolute_trace_paths_for_explicit_tracepack_outside_outputs(
    monkeypatch,
    tmp_path,
) -> None:
    tracepack_path = (tmp_path / "explicit.tracepack.json").resolve()
    trace_root = tracepack_path.with_suffix("")
    trace_path = (trace_root / "traces" / "plunge_low_half_0.trace.json").resolve()
    preview_path = (trace_root / "previews" / "plunge_low_half_0.png").resolve()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("{}", encoding="utf-8")
    preview_path.write_bytes(b"png")

    monkeypatch.setattr(
        run_batch_module,
        "resolve_benchmark_plan",
        lambda _cfg: [
            ResolvedBenchRun(
                0,
                "plunge",
                "low:half",
                "plunge",
                "low:half",
                "landing",
                run_key="plunge:low:half:0",
            )
        ],
    )
    monkeypatch.setattr(run_batch_module, "print_batch_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_batch_module,
        "_run_batch_sequential",
        lambda *_args, **_kwargs: [
            {
                "bot": "pdg",
                "level": "plunge",
                "scenario": "low:half",
                "eval_goal": "landing",
                "seed": 0,
                "success": True,
                "state": "landed",
                "failure_mode": "none",
                "trace_path": str(trace_path),
                "trace_rel_path": None,
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": None,
                "run_key": "plunge:low:half:0",
                "run_instance_id": 1,
            }
        ],
    )
    monkeypatch.setattr(
        run_batch_module,
        "aggregate_eval_records",
        lambda _records: {
            "runs": 1,
            "successes": 1,
            "landed": 1,
            "crashed": 0,
            "out_of_fuel": 0,
            "flying": 0,
            "other": 0,
            "success_rate": 1.0,
            "efficiency_success": {},
            "efficiency_all": {},
            "by_scenario": {},
            "by_selector": {},
        },
    )

    cfg = BenchSettings(
        bot_name="pdg",
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="plunge",
                scenario_name="low:half",
                scenario_path=("low", "half"),
                seed_spec="0",
            ),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=1,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path=str(tracepack_path),
    )

    exit_code = run_batch_module.run_benchmark(cfg)
    payload = json.loads(tracepack_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["trace_root_path"] == str(trace_root)
    assert payload["trace_root_rel"] is None
    assert payload["records"][0]["trace_path"] == str(trace_path)
    assert payload["records"][0]["trace_rel_path"] is None
    assert payload["run_index"][0]["trace_path"] == str(trace_path)
    assert payload["run_index"][0]["trace_preview_path"] == str(preview_path)
    assert payload["run_index"][0]["run_key"] == "plunge:low:half:0"


def test_run_benchmark_auto_tracepack_uses_absolute_root_and_outputs_relative_root(
    monkeypatch,
    tmp_path,
) -> None:
    outputs_root = (tmp_path / "outputs").resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        run_batch_module,
        "resolve_benchmark_plan",
        lambda _cfg: [
            ResolvedBenchRun(
                0,
                "plunge",
                "low:half",
                "plunge",
                "low:half",
                "landing",
                run_key="plunge:low:half:0",
            )
        ],
    )
    monkeypatch.setattr(run_batch_module, "print_batch_summary", lambda *_args, **_kwargs: None)

    def _fake_run_batch_sequential(run_settings, _run_plan, *, benchmark_mode):  # type: ignore[no-untyped-def]
        _ = benchmark_mode
        trace_root = Path(str(run_settings.trace_root_dir)).resolve()
        trace_path = (trace_root / "traces" / "plunge_low_half_0.trace.json").resolve()
        preview_path = (trace_root / "previews" / "plunge_low_half_0.png").resolve()
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("{}", encoding="utf-8")
        preview_path.write_bytes(b"png")
        return [
            {
                "bot": "pdg",
                "level": "plunge",
                "scenario": "low:half",
                "eval_goal": "landing",
                "seed": 0,
                "success": True,
                "state": "landed",
                "failure_mode": "none",
                "trace_path": str(trace_path),
                "trace_rel_path": trace_path.relative_to(outputs_root).as_posix(),
                "trace_preview_path": str(preview_path),
                "trace_preview_rel_path": preview_path.relative_to(outputs_root).as_posix(),
                "run_key": "plunge:low:half:0",
                "run_instance_id": 1,
            }
        ]

    monkeypatch.setattr(run_batch_module, "_run_batch_sequential", _fake_run_batch_sequential)
    monkeypatch.setattr(
        run_batch_module,
        "aggregate_eval_records",
        lambda _records: {
            "runs": 1,
            "successes": 1,
            "landed": 1,
            "crashed": 0,
            "out_of_fuel": 0,
            "flying": 0,
            "other": 0,
            "success_rate": 1.0,
            "efficiency_success": {},
            "efficiency_all": {},
            "by_scenario": {},
            "by_selector": {},
        },
    )

    cfg = BenchSettings(
        bot_name="pdg",
        bot_config_path=None,
        selectors=(
            BenchTarget(
                level_name="plunge",
                scenario_name="low:half",
                scenario_path=("low", "half"),
                seed_spec="0",
            ),
        ),
        lander_name=None,
        workers=1,
        max_time=300.0,
        max_steps=1,
        trace_enabled=True,
        trace_sample_period_s=0.25,
        json_path="auto",
    )

    exit_code = run_batch_module.run_benchmark(cfg)
    generated = max(outputs_root.glob("*.tracepack.json"), key=lambda path: path.stat().st_mtime)
    payload = json.loads(generated.read_text(encoding="utf-8"))
    trace_root = generated.with_suffix("")

    assert exit_code == 0
    assert payload["trace_root_path"] == str(trace_root.resolve())
    assert payload["trace_root_rel"] == trace_root.resolve().relative_to(outputs_root).as_posix()
    assert payload["records"][0]["trace_rel_path"] == (
        trace_root.resolve().relative_to(outputs_root).as_posix()
        + "/traces/plunge_low_half_0.trace.json"
    )


def test_plot_command_enables_trace_by_default() -> None:
    _parser, command = parse_command(["plot", "boost:flat:far:half:3", "--bot", "pdg"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "boost"
    assert command.run.scenario_name == "flat:far:half"
    assert command.run.runtime_level_name == "boost"
    assert command.run.runtime_scenario_name == "flat:far:half"
    assert command.run.seed == 3
    assert command.run.trace_enabled is True
    assert command.run.trace_sample_period_s == 0.25
