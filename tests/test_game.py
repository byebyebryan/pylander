from __future__ import annotations

import argparse

import pytest

import main as main_module
from bots import create_bot, list_available_bots
from core.components import PhysicsState, Transform
from core.ecs import require_component
from core.eval import aggregate_eval_records, normalize_run_result
from game import LanderGame
from levels import create_level as create_level_by_name, list_available_levels
from main import RunConfig, _parse_args, _parse_seed_spec, _resolve_batch_plan
from ui.hud import HudOverlay


def test_bot_registry_exposes_only_supported_bots() -> None:
    bots = list_available_bots()
    assert "plunge" in bots
    assert "zem_zev" in bots
    assert "coast" not in bots
    assert "flare" not in bots
    assert "setup" not in bots
    assert "launch" not in bots

    plunge_bot = create_bot("plunge")
    zem_bot = create_bot("zem_zev")
    assert plunge_bot.__class__.__name__ == "PlungeBot"
    assert zem_bot.__class__.__name__ == "ZemZevBot"


def test_level_registry_still_includes_phase_levels() -> None:
    levels = list_available_levels()
    for name in ("plunge", "flare", "coast", "setup", "launch"):
        assert name in levels


def test_coast_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("coast")
    assert level.list_batch_scenarios() == [
        "shallower_tight",
        "shallower_wide",
        "shallow_tight",
        "shallow_wide",
        "mid_tight",
        "mid_wide",
        "steep_tight",
        "steep_wide",
        "steeper_tight",
        "steeper_wide",
    ]
    assert level.list_quick_benchmark_scenarios() == [
        "shallow_tight",
        "mid_wide",
        "steep_wide",
    ]


def test_setup_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("setup")
    assert level.list_batch_scenarios() == [
        "shallower_near",
        "shallower_far",
        "shallow_near",
        "shallow_far",
        "mid_near",
        "mid_far",
        "steep_near",
        "steep_far",
        "steeper_near",
        "steeper_far",
    ]
    assert level.list_quick_benchmark_scenarios() == [
        "shallow_near",
        "mid_far",
        "steep_far",
    ]


def test_setup_and_coast_reject_unknown_eval_mode() -> None:
    setup = create_level_by_name("setup")
    with pytest.raises(ValueError, match="Unknown setup eval mode"):
        setup.set_eval_mode("bad")

    coast = create_level_by_name("coast")
    with pytest.raises(ValueError, match="Unknown coast eval mode"):
        coast.set_eval_mode("bad")


def _spawn_state(level_name: str, scenario: str, seed: int) -> tuple[float, float, float, float, float]:
    level = create_level_by_name(level_name)
    level.set_eval_scenario(scenario)
    game = LanderGame(level=level, seed=seed, bot=create_bot("zem_zev"), headless=True)
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


def test_setup_and_coast_scenarios_are_seed_deterministic() -> None:
    setup_a = _spawn_state("setup", "mid_near", 42)
    setup_b = _spawn_state("setup", "mid_near", 42)
    assert setup_a == pytest.approx(setup_b)

    coast_a = _spawn_state("coast", "mid_tight", 42)
    coast_b = _spawn_state("coast", "mid_tight", 42)
    assert coast_a == pytest.approx(coast_b)


def test_setup_focused_eval_uses_zem_gate_only(monkeypatch) -> None:
    level = create_level_by_name("setup")
    level.set_eval_mode("focused")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)

    def _snapshot(_game):
        return {
            "kind": "zem_zev",
            "setup_gate_done": True,
            "setup_gate_time": 5.5,
            "setup_gate_altitude": 123.0,
            "setup_gate_projected_dx": 8.0,
            "terminal_gate_done": False,
        }

    monkeypatch.setattr(level, "_resolve_zem_snapshot", _snapshot)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game)

    result = level.end(game)
    assert result["eval_phase"] == "zem_setup_gate"
    assert result["success"] is True
    assert result["setup_phase_done"] is True
    assert result["setup_phase_time"] == pytest.approx(5.5)
    assert result["setup_phase_altitude"] == pytest.approx(123.0)


def test_coast_focused_eval_uses_zem_gate_only(monkeypatch) -> None:
    level = create_level_by_name("coast")
    level.set_eval_mode("focused")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)

    def _snapshot(_game):
        return {
            "kind": "zem_zev",
            "setup_gate_done": True,
            "terminal_gate_done": True,
            "terminal_gate_time": 7.25,
            "terminal_gate_altitude": 88.0,
            "terminal_gate_projected_dx": 5.0,
        }

    monkeypatch.setattr(level, "_resolve_zem_snapshot", _snapshot)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game)

    result = level.end(game)
    assert result["eval_phase"] == "zem_terminal_gate"
    assert result["success"] is True
    assert result["coast_phase_done"] is True
    assert result["coast_phase_time"] == pytest.approx(7.25)
    assert result["coast_phase_altitude"] == pytest.approx(88.0)


def test_normalize_run_result_includes_new_phase_fields() -> None:
    record = normalize_run_result(
        bot_name="zem_zev",
        level_name="setup",
        scenario="mid_near",
        seed=3,
        result={
            "state": "flying",
            "success": True,
            "setup_phase_done": True,
            "setup_phase_time": 6.0,
            "setup_phase_altitude": 120.0,
            "setup_phase_projected_dx": 9.0,
            "setup_phase_distance": 150.0,
            "setup_phase_fuel_consumed": 11.0,
            "setup_phase_fuel_per_distance": 0.073,
            "coast_phase_done": False,
            "coast_phase_distance": 0.0,
        },
    )
    assert record["success"] is True
    assert record["setup_phase_done"] is True
    assert record["setup_phase_time"] == pytest.approx(6.0)
    assert record["setup_phase_distance"] == pytest.approx(150.0)
    assert record["coast_phase_done"] is False


def test_eval_aggregate_uses_explicit_success_for_staged_records() -> None:
    records = [
        normalize_run_result(
            bot_name="zem_zev",
            level_name="setup",
            scenario="mid_near",
            seed=0,
            result={
                "state": "flying",
                "success": True,
                "setup_phase_done": True,
                "setup_phase_time": 6.0,
                "setup_phase_distance": 180.0,
                "setup_phase_fuel_consumed": 12.0,
            },
        )
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 1
    assert summary["successes"] == 1
    assert summary["success_rate"] == pytest.approx(1.0)
    assert summary["by_scenario"]["mid_near"]["success_rate"] == pytest.approx(1.0)


def test_parse_seed_spec_keeps_order_and_deduplicates() -> None:
    assert _parse_seed_spec("0-2,2,5,4-3") == [0, 1, 2, 5, 4, 3]


def test_parse_args_drops_bot_behavior_support() -> None:
    parser = main_module._build_parser()
    args = parser.parse_args(["plunge", "--headless", "--bot", "plunge"])
    config = _parse_args(args)
    assert isinstance(config, RunConfig)
    assert config.bot_name == "plunge"
    assert not hasattr(config, "bot_behavior")


def test_parser_rejects_removed_bot_behavior_flag() -> None:
    parser = main_module._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["plunge", "--bot-behavior", "balanced"])


def test_resolve_batch_plan_quick_benchmark_uses_expected_levels(monkeypatch) -> None:
    config = RunConfig(
        level_name="plunge",
        bot_name=None,
        headless=True,
        batch=False,
        print_freq=0,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        stop_on_crash=True,
        stop_on_out_of_fuel=True,
        stop_on_first_land=True,
        seed=None,
        lander_name=None,
        batch_seeds=None,
        batch_levels=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=True,
        batch_workers=1,
        eval_mode="auto",
        scenario_name=None,
        batch_scenarios=None,
    )

    monkeypatch.setattr(main_module, "_list_quick_benchmark_levels", lambda: ["plunge", "flare", "coast", "setup"])
    seeds, levels = _resolve_batch_plan(config)
    assert seeds == [0]
    assert levels == ["plunge", "flare", "coast", "setup"]


def test_hud_display_state_falls_back_to_status_parse() -> None:
    class _Bot:
        def get_status(self) -> str:
            return "zem_zev:terminal dx: 12.3"

    active, stage = HudOverlay._resolve_bot_display_state(_Bot(), _Bot().get_status())
    assert active == "zem_zev"
    assert stage == "terminal"


def test_parse_args_eval_mode_default_is_auto() -> None:
    args = argparse.Namespace(
        level_name="plunge",
        bot=None,
        headless=False,
        batch=False,
        freq=None,
        time=None,
        steps=None,
        plot=None,
        stop_on_crash=False,
        stop_on_out_of_fuel=False,
        stop_on_first_land=False,
        eval_mode="auto",
        seed=None,
        scenario=None,
        lander=None,
        batch_seeds=None,
        batch_levels=None,
        batch_scenarios=None,
        batch_json=None,
        batch_csv=None,
        quick_benchmark=False,
        batch_workers=None,
    )
    config = _parse_args(args)
    assert config.eval_mode == "auto"
