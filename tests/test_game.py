from __future__ import annotations

import os

import pytest

import app.run_batch as run_batch_module
from app.cli import build_parser, parse_command
from app.config import BenchCommand, BenchSettings, BenchTarget, RunCommand
from bots import create_bot, list_available_bots
from core.bot import QueryBot
from core.components import LandingSite, PhysicsState, Transform
from core.ecs import require_component
from core.eval import aggregate_eval_records, normalize_run_result
from game import LanderGame
from levels import create_level as create_level_by_name, list_available_levels
from app.run_batch import parse_seed_spec, resolve_benchmark_plan
from ui.hud import HudOverlay


def test_bot_registry_exposes_only_supported_bots() -> None:
    bots = list_available_bots()
    assert "plunge" in bots
    assert "query_demo" in bots
    assert "zem_zev" in bots
    assert "coast" not in bots
    assert "flare" not in bots
    assert "setup" not in bots
    assert "launch" not in bots

    plunge_bot = create_bot("plunge")
    query_demo_bot = create_bot("query_demo")
    zem_bot = create_bot("zem_zev")
    assert plunge_bot.__class__.__name__ == "PlungeBot"
    assert query_demo_bot.__class__.__name__ == "QueryDemoBot"
    assert zem_bot.__class__.__name__ == "ZemZevBot"
    assert isinstance(plunge_bot, QueryBot)
    assert isinstance(query_demo_bot, QueryBot)
    assert isinstance(zem_bot, QueryBot)


def test_create_bot_rejects_config_override_for_unsupported_bot() -> None:
    with pytest.raises(ValueError, match="does not support --bot-config"):
        create_bot("plunge", config_override={"setup_gate_projected_dx_abs": 42.0})


def test_create_bot_applies_zem_bot_config_override() -> None:
    bot = create_bot(
        "zem_zev",
        config_override={
            "setup_gate_projected_dx_abs": 42.0,
            "fallback_hold_steps": 10.0,
        },
    )
    cfg = getattr(bot, "_cfg")
    assert float(cfg.setup_gate_projected_dx_abs) == pytest.approx(42.0)
    assert int(cfg.fallback_hold_steps) == 10


def test_level_registry_still_includes_phase_levels() -> None:
    levels = list_available_levels()
    for name in ("plunge", "flare", "coast", "climb", "setup", "launch"):
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


def test_climb_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("climb")
    assert level.list_batch_scenarios() == [
        "slope_low",
        "slope_mid",
        "slope_high",
    ]
    assert level.list_quick_benchmark_scenarios() == [
        "slope_low",
        "slope_mid",
        "slope_high",
    ]


def test_climb_rejects_unknown_scenario() -> None:
    level = create_level_by_name("climb")
    with pytest.raises(ValueError, match="Unknown climb scenario"):
        level.set_eval_scenario("bad")


def test_climb_target_is_terrain_bound_not_supports() -> None:
    level = create_level_by_name("climb")
    level.set_eval_scenario("slope_mid")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    target = next(
        site
        for site in game.level.world.site_entities
        if site.uid == "climb_site_target"
    )
    shape = target.get_component(LandingSite)
    assert shape is not None
    assert shape.terrain_mode == "flush_flatten"
    assert shape.terrain_bound is True


def test_climb_landed_site_uid_requires_pad_overlap() -> None:
    level = create_level_by_name("climb")
    level.set_eval_scenario("slope_mid")
    _game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    target = next(spec for spec in level.site_specs if spec.uid == "climb_site_target")
    half = 0.5 * float(target.size)
    assert level._resolve_landed_site_uid(float(target.x)) == "climb_site_target"
    assert level._resolve_landed_site_uid(float(target.x) + half + 2.0) is None


def test_launch_landed_site_uid_requires_pad_overlap() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("mid")
    _game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    dest = next(spec for spec in level.site_specs if spec.uid == "launch_site_dest")
    half = 0.5 * float(dest.size)
    assert level._resolve_landed_site_uid(float(dest.x)) == "launch_site_dest"
    assert level._resolve_landed_site_uid(float(dest.x) + half + 2.0) is None


def test_setup_coast_and_climb_reject_unknown_eval_mode() -> None:
    setup = create_level_by_name("setup")
    with pytest.raises(ValueError, match="Unknown setup eval mode"):
        setup.set_eval_mode("bad")

    coast = create_level_by_name("coast")
    with pytest.raises(ValueError, match="Unknown coast eval mode"):
        coast.set_eval_mode("bad")

    climb = create_level_by_name("climb")
    with pytest.raises(ValueError, match="Unknown climb eval mode"):
        climb.set_eval_mode("bad")


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

    climb_a = _spawn_state("climb", "slope_mid", 42)
    climb_b = _spawn_state("climb", "slope_mid", 42)
    assert climb_a == pytest.approx(climb_b)


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


def test_climb_focused_eval_uses_zem_gate_only(monkeypatch) -> None:
    level = create_level_by_name("climb")
    level.set_eval_mode("focused")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)

    def _snapshot(_game):
        return {
            "kind": "zem_zev",
            "setup_gate_done": True,
            "setup_gate_time": 4.75,
            "setup_gate_altitude": 145.0,
            "setup_gate_projected_dx": 12.0,
        }

    monkeypatch.setattr(level, "_resolve_zem_snapshot", _snapshot)
    level.update(game, 1.0 / 60.0)
    assert level.should_end(game)

    result = level.end(game)
    assert result["eval_phase"] == "zem_setup_gate"
    assert result["success"] is True
    assert result["climb_phase_done"] is True
    assert result["climb_phase_time"] == pytest.approx(4.75)
    assert result["climb_phase_altitude"] == pytest.approx(145.0)


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
            "climb_phase_done": True,
            "climb_phase_time": 5.5,
            "climb_phase_distance": 132.0,
            "climb_arrived": False,
            "zem_clearance_margin": 72.0,
            "zem_clearance_scale": 0.85,
            "zem_clearance_active": True,
            "zem_shape_window_started": True,
            "zem_shape_window_done": True,
            "zem_shape_window_start_time": 0.4,
            "zem_shape_window_end_time": 8.6,
            "zem_shape_apex_target_over_target": 120.0,
            "zem_shape_apex_actual_over_target": 116.0,
            "zem_shape_apex_error": 4.0,
            "zem_shape_curve_rmse": 14.5,
            "zem_shape_projected_dx_abs_mean": 18.0,
            "zem_shape_projected_dx_abs_max": 41.0,
            "zem_shape_shortfall_ratio": 0.12,
        },
    )
    assert record["success"] is True
    assert record["setup_phase_done"] is True
    assert record["setup_phase_time"] == pytest.approx(6.0)
    assert record["setup_phase_distance"] == pytest.approx(150.0)
    assert record["coast_phase_done"] is False
    assert record["climb_phase_done"] is True
    assert record["climb_phase_time"] == pytest.approx(5.5)
    assert record["climb_phase_distance"] == pytest.approx(132.0)
    assert record["climb_arrived"] is False
    assert record["zem_clearance_margin"] == pytest.approx(72.0)
    assert record["zem_clearance_scale"] == pytest.approx(0.85)
    assert record["zem_clearance_active"] is True
    assert record["zem_shape_window_started"] is True
    assert record["zem_shape_window_done"] is True
    assert record["zem_shape_window_start_time"] == pytest.approx(0.4)
    assert record["zem_shape_window_end_time"] == pytest.approx(8.6)
    assert record["zem_shape_apex_target_over_target"] == pytest.approx(120.0)
    assert record["zem_shape_apex_actual_over_target"] == pytest.approx(116.0)
    assert record["zem_shape_apex_error"] == pytest.approx(4.0)
    assert record["zem_shape_curve_rmse"] == pytest.approx(14.5)
    assert record["zem_shape_projected_dx_abs_mean"] == pytest.approx(18.0)
    assert record["zem_shape_projected_dx_abs_max"] == pytest.approx(41.0)
    assert record["zem_shape_shortfall_ratio"] == pytest.approx(0.12)


def test_launch_run_merges_zem_snapshot_fields_into_result() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("near")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    result = game.run(print_freq=0, max_steps=2, max_time=2.0)
    assert "zem_phase" in result
    assert "zem_shape_window_started" in result


def test_launch_setup_gate_latches_no_later_than_terminal_gate() -> None:
    level = create_level_by_name("launch")
    level.set_eval_scenario("far")
    game = LanderGame(level=level, seed=1, bot=create_bot("zem_zev"), headless=True)
    result = game.run(print_freq=0, max_time=120.0)
    setup_gate_time = result.get("zem_setup_gate_time")
    terminal_gate_time = result.get("zem_terminal_gate_time")
    assert setup_gate_time is not None
    if terminal_gate_time is not None:
        assert float(setup_gate_time) <= float(terminal_gate_time) + 1e-6


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
    assert parse_seed_spec("0-2,2,5,4-3") == [0, 1, 2, 5, 4, 3]


def test_parse_args_drops_bot_behavior_support() -> None:
    _parser, command = parse_command(["run", "plunge", "--bot", "plunge"])
    assert isinstance(command, RunCommand)
    assert command.run.bot_name == "plunge"


def test_parser_rejects_removed_bot_behavior_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "plunge", "--bot-behavior", "balanced"])


def test_resolve_batch_plan_expands_all_scenarios_without_seed_spec(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(BenchTarget(level_name="plunge", scenario_name=None, seed_spec=None),),
        lander_name=None,
        eval_mode="auto",
        workers=1,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        plot_output="combined",
        plot_max_side_px=1800,
        json_path=None,
        csv_path=None,
    )

    monkeypatch.setattr(
        run_batch_module,
        "resolve_level_scenarios",
        lambda _name: ["low_normal", "mid_normal"],
    )
    monkeypatch.setattr(run_batch_module, "_scenario_has_randomized_fields", lambda _l, _s: False)
    plan = resolve_benchmark_plan(config)
    assert plan == [
        (0, "plunge", "low_normal"),
        (0, "plunge", "mid_normal"),
    ]


def test_resolve_batch_plan_honors_selector_seed_spec(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(BenchTarget(level_name="launch", scenario_name="far", seed_spec="0-2,2"),),
        lander_name=None,
        eval_mode="auto",
        workers=1,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        plot_output="combined",
        plot_max_side_px=1800,
        json_path=None,
        csv_path=None,
    )
    monkeypatch.setattr(run_batch_module, "_scenario_has_randomized_fields", lambda _l, _s: False)
    plan = resolve_benchmark_plan(config)
    assert plan == [
        (0, "launch", "far"),
        (1, "launch", "far"),
        (2, "launch", "far"),
    ]


def test_hud_display_state_falls_back_to_status_parse() -> None:
    class _Bot:
        def get_status(self) -> str:
            return "zem_zev:terminal dx: 12.3"

    active, stage = HudOverlay._resolve_bot_display_state(_Bot(), _Bot().get_status())
    assert active == "zem_zev"
    assert stage == "terminal"


def test_hud_display_state_prefers_phase_token() -> None:
    class _Bot:
        def get_status(self) -> str:
            return "zem_zev:opt ph:setup dx: 12.3 pdx: -4.0"

    active, stage = HudOverlay._resolve_bot_display_state(_Bot(), _Bot().get_status())
    assert active == "zem_zev"
    assert stage == "setup"


def test_parse_args_eval_mode_default_is_auto() -> None:
    _parser, command = parse_command(["sim", "plunge"])
    assert isinstance(command, RunCommand)
    assert command.run.eval_mode == "auto"


def test_cli_requires_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parse_bench_command_uses_expected_defaults() -> None:
    _parser, command = parse_command(["bench", "plunge"])
    assert isinstance(command, BenchCommand)
    assert command.bench.selectors == (
        BenchTarget(level_name="plunge", scenario_name=None, seed_spec=None),
    )
    assert command.bench.eval_mode == "auto"
    assert command.bench.workers == max(1, int(os.cpu_count() or 1) - 2)
    assert command.bench.plot_output == "combined"
    assert command.bench.plot_max_side_px == 1800
    assert command.bench.bot_profile_enabled is True
    assert command.bench.bot_profile_log_lines is False
    assert command.bench.bot_profile_interval_s is None


def test_parse_bench_command_rejects_workers_override() -> None:
    with pytest.raises(SystemExit):
        parse_command(["bench", "plunge", "--workers", "1"])


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


def test_parse_bench_command_plot_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "bench",
            "plunge",
            "--plot",
            "all",
            "--plot-output",
            "split",
            "--plot-max-side-px",
            "1400",
        ]
    )
    assert isinstance(command, BenchCommand)
    assert command.bench.plot_mode == "all"
    assert command.bench.plot_output == "split"
    assert command.bench.plot_max_side_px == 1400


def test_parse_plot_command_output_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "plot",
            "launch:far:3",
            "--bot",
            "zem_zev",
            "--plot-output",
            "both",
            "--plot-max-side-px",
            "1400",
        ]
    )
    assert isinstance(command, RunCommand)
    assert command.run.plot_output == "both"
    assert command.run.plot_max_side_px == 1400


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
        lambda _cfg: [(0, "launch", "mid"), (1, "launch", "mid")],
    )

    cfg = BenchSettings(
        bot_name="zem_zev",
        bot_config_path=None,
        selectors=(BenchTarget(level_name="launch", scenario_name="mid", seed_spec="0"),),
        lander_name=None,
        eval_mode="auto",
        workers=4,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        plot_output="combined",
        plot_max_side_px=1800,
        json_path=None,
        csv_path=None,
    )
    with pytest.raises(RuntimeError, match="run 1/2 seed=0 level=launch scenario=mid failed"):
        run_batch_module.run_benchmark(cfg)


def test_plot_command_enables_plot_mode_by_default() -> None:
    _parser, command = parse_command(["plot", "launch:far:3", "--bot", "zem_zev"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "launch"
    assert command.run.scenario_name == "far"
    assert command.run.seed == 3
    assert command.run.plot_mode == "all"
    assert command.run.plot_output == "combined"
    assert command.run.plot_max_side_px == 1800
