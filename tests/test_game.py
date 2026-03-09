from __future__ import annotations

import os

import pytest

import app.run_batch as run_batch_module
from app.cli import build_parser, parse_command
from app.config import BenchCommand, BenchSettings, BenchTarget, RunCommand
from bots import create_bot, list_available_bots
from core.bot import Bot, BotAction, Sensors, resolve_bot_display_state
from core.components import LandingSite, PhysicsState, Transform
from core.ecs import require_component
from core.eval import aggregate_eval_records, normalize_run_result
from game import LanderGame
from levels import create_level as create_level_by_name, list_available_levels
from app.run_batch import ResolvedBenchRun, parse_seed_spec, resolve_benchmark_plan
from core.bot import BotDisplayState


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
    assert isinstance(plunge_bot, Bot)
    assert isinstance(zem_bot, Bot)


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
    for name in (
        "flare_plunge",
        "flare_normal",
        "flare_error",
        "setup_downhill",
        "setup_flat",
        "setup_climb",
    ):
        assert name in levels


def test_flare_error_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("flare_error")
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


def test_setup_downhill_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("setup_downhill")
    assert level.list_batch_scenarios() == ["low", "mid", "high"]
    assert level.list_quick_benchmark_scenarios() == ["low", "mid", "high"]


def test_setup_climb_level_scenario_names_are_clean_and_prefixed_removed() -> None:
    level = create_level_by_name("setup_climb")
    assert level.list_batch_scenarios() == ["low", "mid", "high"]
    assert level.list_quick_benchmark_scenarios() == ["low", "mid", "high"]


def test_setup_climb_rejects_unknown_scenario() -> None:
    level = create_level_by_name("setup_climb")
    with pytest.raises(ValueError, match="Unknown setupclimb scenario"):
        level.set_eval_scenario("bad")


def test_setup_climb_target_is_terrain_bound_flush_pad() -> None:
    level = create_level_by_name("setup_climb")
    level.set_eval_scenario("mid")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    target = next(
        site
        for site in game.level.world.site_entities
        if site.uid == "setup_transfer_target"
    )
    shape = target.get_component(LandingSite)
    assert shape is not None
    assert shape.terrain_mode == "flush_flatten"
    assert shape.terrain_bound is True


@pytest.mark.parametrize("level_name", ["setup_climb", "setup_flat", "setup_downhill"])
def test_landed_site_uid_requires_pad_overlap(level_name: str) -> None:
    level = create_level_by_name(level_name)
    level.set_eval_scenario("mid")
    _game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    target = next(spec for spec in level.site_specs if spec.uid == "setup_transfer_target")
    half = 0.5 * float(target.size)
    assert level._resolve_landed_site_uid(float(target.x)) == "setup_transfer_target"
    assert level._resolve_landed_site_uid(float(target.x) + half + 2.0) is None


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


def test_setup_and_flare_error_scenarios_are_seed_deterministic() -> None:
    setup_a = _spawn_state("setup_downhill", "mid", 42)
    setup_b = _spawn_state("setup_downhill", "mid", 42)
    assert setup_a == pytest.approx(setup_b)

    coast_a = _spawn_state("flare_error", "mid_tight", 42)
    coast_b = _spawn_state("flare_error", "mid_tight", 42)
    assert coast_a == pytest.approx(coast_b)

    climb_a = _spawn_state("setup_climb", "mid", 42)
    climb_b = _spawn_state("setup_climb", "mid", 42)
    assert climb_a == pytest.approx(climb_b)


def test_zem_setup_goal_ends_headless_run_early() -> None:
    level = create_level_by_name("setup_downhill")
    level.set_eval_scenario("mid")
    bot = create_bot("zem_zev")
    bot.set_eval_goal("setup")
    game = LanderGame(level=level, seed=0, bot=bot, headless=True, eval_goal="setup")

    result = game.run(print_freq=0, max_time=120.0)
    assert result["eval_goal"] == "setup"
    assert result["eval_early_end"] is True
    assert result["success"] is True
    assert result["failure_mode"] == "none"
    assert result["setup_gate_done"] is True
    assert result["setup_goal_done"] is True
    assert result["setup_goal_has_target_y_solution"] is True
    assert result["setup_goal_projected_impact_angle_deg"] is not None


def test_non_landing_goal_without_decision_fails_goal_not_reached() -> None:
    class _NoGoalBot(Bot):
        def set_eval_goal(self, goal: str) -> None:
            key = str(goal or "landing").strip().lower()
            if key not in {"landing", "setup"}:
                raise ValueError("unsupported goal")
            self._eval_goal = key

        def update(self, dt: float, sensors: Sensors) -> BotAction:
            _ = dt, sensors
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    bot = _NoGoalBot()
    bot.set_eval_goal("setup")
    game = LanderGame(
        level=create_level_by_name("flat"),
        seed=0,
        bot=bot,
        headless=True,
        eval_goal="setup",
    )
    result = game.run(print_freq=0, max_steps=5, max_time=5.0)

    assert result["eval_goal"] == "setup"
    assert result["eval_early_end"] is False
    assert result["success"] is False
    assert result["failure_mode"] == "goal_not_reached"


def test_normalize_run_result_uses_canonical_eval_fields() -> None:
    record = normalize_run_result(
        bot_name="zem_zev",
        level_name="setup_downhill",
        scenario="mid",
        seed=3,
        result={
            "state": "flying",
            "success": True,
            "eval_goal": "setup",
            "eval_early_end": True,
            "eval_end_reason": "goal_reached",
            "setup_goal_done": True,
            "setup_goal_time": 6.0,
            "setup_goal_altitude": 120.0,
            "setup_goal_projected_apex_y": 180.0,
            "setup_goal_projected_apex_over_target": 60.0,
            "setup_goal_has_target_y_solution": True,
            "setup_goal_projected_dx": 8.0,
            "setup_goal_projected_impact_angle_deg": 57.0,
            "setup_goal_burn_avg_thrust_level": 0.84,
            "setup_gate_done": True,
            "setup_gate_time": 6.0,
            "setup_gate_altitude": 120.0,
            "setup_gate_projected_apex_y": 180.0,
            "setup_gate_projected_apex_over_target": 60.0,
            "setup_gate_has_target_y_solution": True,
            "setup_gate_projected_dx": 8.0,
            "setup_gate_projected_impact_angle_deg": 57.0,
            "setup_gate_burn_duration_s": 6.0,
            "setup_gate_burn_fuel_used": 17.0,
            "setup_gate_burn_avg_thrust_level": 0.84,
            "setup_transfer_arrived": False,
            "bot_zem_zev_terminal_gate_done": True,
            "bot_zem_zev_terminal_gate_time": 8.6,
            "bot_zem_zev_terminal_gate_altitude": 72.0,
            "bot_zem_zev_terminal_gate_projected_dx": 4.5,
            "bot_zem_zev_solve_count": 32,
            "bot_zem_zev_solve_ms_mean": 3.2,
            "bot_zem_zev_solve_ms_p90": 7.4,
            "bot_zem_zev_fallback_frames": 1,
            "bot_zem_zev_shape_apex_error": 4.0,
            "bot_zem_zev_shape_curve_rmse": 14.5,
            "bot_zem_zev_shape_projected_dx_abs_mean": 18.0,
            "bot_zem_zev_shape_projected_dx_abs_max": 41.0,
            "bot_zem_zev_shape_shortfall_ratio": 0.12,
        },
    )
    assert record["success"] is True
    assert record["eval_goal"] == "setup"
    assert record["eval_early_end"] is True
    assert record["eval_end_reason"] == "goal_reached"
    assert record["setup_goal_done"] is True
    assert record["setup_goal_time"] == pytest.approx(6.0)
    assert record["setup_goal_altitude"] == pytest.approx(120.0)
    assert record["setup_goal_projected_apex_over_target"] == pytest.approx(60.0)
    assert record["setup_goal_has_target_y_solution"] is True
    assert record["setup_goal_projected_dx"] == pytest.approx(8.0)
    assert record["setup_goal_projected_impact_angle_deg"] == pytest.approx(57.0)
    assert record["setup_gate_done"] is True
    assert record["setup_gate_burn_duration_s"] == pytest.approx(6.0)
    assert record["setup_gate_burn_fuel_used"] == pytest.approx(17.0)
    assert record["setup_transfer_arrived"] is False
    assert record["bot_zem_zev_terminal_gate_done"] is True
    assert record["bot_zem_zev_terminal_gate_time"] == pytest.approx(8.6)
    assert record["bot_zem_zev_terminal_gate_altitude"] == pytest.approx(72.0)
    assert record["bot_zem_zev_terminal_gate_projected_dx"] == pytest.approx(4.5)
    assert record["bot_zem_zev_solve_count"] == pytest.approx(32.0)
    assert record["bot_zem_zev_solve_ms_mean"] == pytest.approx(3.2)
    assert record["bot_zem_zev_solve_ms_p90"] == pytest.approx(7.4)
    assert record["bot_zem_zev_fallback_frames"] == pytest.approx(1.0)
    assert record["bot_zem_zev_shape_apex_error"] == pytest.approx(4.0)
    assert record["bot_zem_zev_shape_curve_rmse"] == pytest.approx(14.5)
    assert record["bot_zem_zev_shape_projected_dx_abs_mean"] == pytest.approx(18.0)
    assert record["bot_zem_zev_shape_projected_dx_abs_max"] == pytest.approx(41.0)
    assert record["bot_zem_zev_shape_shortfall_ratio"] == pytest.approx(0.12)


def test_setup_flat_run_merges_bot_telemetry_fields_into_result() -> None:
    level = create_level_by_name("setup_flat")
    level.set_eval_scenario("near")
    game = LanderGame(level=level, seed=0, bot=create_bot("zem_zev"), headless=True)
    result = game.run(print_freq=0, max_steps=2, max_time=2.0)
    assert "bot_zem_zev_solve_count" in result
    assert "bot_zem_zev_shape_curve_rmse" in result


def test_eval_aggregate_uses_explicit_success_for_staged_records() -> None:
    records = [
        normalize_run_result(
            bot_name="zem_zev",
            level_name="setup_downhill",
            scenario="mid",
            seed=0,
            result={
                "state": "flying",
                "success": True,
                "eval_goal": "setup",
                "eval_early_end": True,
                "setup_goal_done": True,
                "setup_goal_time": 6.0,
            },
        )
    ]
    summary = aggregate_eval_records(records)
    assert summary["runs"] == 1
    assert summary["successes"] == 1
    assert summary["success_rate"] == pytest.approx(1.0)
    assert summary["by_scenario"]["mid"]["success_rate"] == pytest.approx(1.0)
    assert summary["by_selector"]["setup_downhill:mid:setup"]["success_rate"] == pytest.approx(1.0)


def test_parse_seed_spec_keeps_order_and_deduplicates() -> None:
    assert parse_seed_spec("0-2,2,5,4-3") == [0, 1, 2, 5, 4, 3]


def test_parser_rejects_removed_bot_behavior_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "flare_plunge", "--bot-behavior", "balanced"])


def test_resolve_batch_plan_expands_all_scenarios_without_seed_spec(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(BenchTarget(level_name="flare_plunge", scenario_name=None, seed_spec=None),),
        lander_name=None,
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
        ResolvedBenchRun(0, "flare_plunge", "low_normal", "landing"),
        ResolvedBenchRun(0, "flare_plunge", "mid_normal", "landing"),
    ]


def test_resolve_batch_plan_honors_selector_seed_spec(monkeypatch) -> None:
    config = BenchSettings(
        bot_name=None,
        bot_config_path=None,
        selectors=(BenchTarget(level_name="setup_flat", scenario_name="far", seed_spec="0-2,2"),),
        lander_name=None,
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
        ResolvedBenchRun(0, "setup_flat", "far", "landing"),
        ResolvedBenchRun(1, "setup_flat", "far", "landing"),
        ResolvedBenchRun(2, "setup_flat", "far", "landing"),
    ]


def test_hud_display_state_returns_none_when_display_state_is_missing() -> None:
    class _Bot:
        pass

    assert resolve_bot_display_state(_Bot()) is None


def test_hud_display_state_prefers_structured_display_state() -> None:
    class _Bot:
        def get_display_state(self):
            return BotDisplayState(
                bot_name="zem_zev",
                mode="opt",
                phase="setup",
                summary="dx=12.3 pdx=-4.0",
            )

    display = resolve_bot_display_state(_Bot())
    assert display is not None
    assert display.bot_name == "zem_zev"
    assert display.phase == "setup"


def test_parse_args_accepts_level_goal_selector() -> None:
    _parser, command = parse_command(["sim", "setup_downhill:mid:setup:0", "--bot", "zem_zev"])
    assert isinstance(command, RunCommand)
    assert command.run.bot_name == "zem_zev"
    assert command.run.eval_goal == "setup"


def test_cli_requires_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parse_play_command_uses_interactive_defaults() -> None:
    _parser, command = parse_command(["play"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "flat"
    assert command.run.headless is False
    assert command.run.plot_mode == "none"
    assert command.run.plot_output == "combined"
    assert command.run.plot_max_side_px == 1800


def test_parse_play_command_accepts_selector_and_bot() -> None:
    _parser, command = parse_command(["play", "setup_flat:far:3", "--bot", "zem_zev"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "setup_flat"
    assert command.run.scenario_name == "far"
    assert command.run.seed == 3
    assert command.run.bot_name == "zem_zev"
    assert command.run.headless is False


def test_parse_bench_command_uses_expected_defaults() -> None:
    _parser, command = parse_command(["bench", "flare_plunge"])
    assert isinstance(command, BenchCommand)
    assert command.bench.selectors == (
        BenchTarget(level_name="flare_plunge", scenario_name=None, seed_spec=None),
    )
    assert command.bench.workers == max(1, int(os.cpu_count() or 1) - 2)
    assert command.bench.plot_output == "combined"
    assert command.bench.plot_max_side_px == 1800
    assert command.bench.bot_profile_enabled is True
    assert command.bench.bot_profile_log_lines is False
    assert command.bench.bot_profile_interval_s is None


def test_parse_bench_command_rejects_workers_override() -> None:
    with pytest.raises(SystemExit):
        parse_command(["bench", "flare_plunge", "--workers", "1"])


def test_parse_bench_command_profile_flags_override_defaults() -> None:
    _parser, command = parse_command(
        [
            "bench",
            "flare_plunge",
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
            "flare_plunge",
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
            "setup_flat:far:3",
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
        lambda _cfg: [
            ResolvedBenchRun(0, "setup_flat", "mid", "landing"),
            ResolvedBenchRun(1, "setup_flat", "mid", "landing"),
        ],
    )

    cfg = BenchSettings(
        bot_name="zem_zev",
        bot_config_path=None,
        selectors=(BenchTarget(level_name="setup_flat", scenario_name="mid", seed_spec="0"),),
        lander_name=None,
        workers=4,
        max_time=300.0,
        max_steps=None,
        plot_mode="none",
        plot_output="combined",
        plot_max_side_px=1800,
        json_path=None,
        csv_path=None,
    )
    with pytest.raises(
        RuntimeError,
        match="run 1/2 seed=0 level=setup_flat scenario=mid failed",
    ):
        run_batch_module.run_benchmark(cfg)


def test_plot_command_enables_plot_mode_by_default() -> None:
    _parser, command = parse_command(["plot", "setup_flat:far:3", "--bot", "zem_zev"])
    assert isinstance(command, RunCommand)
    assert command.run.level_name == "setup_flat"
    assert command.run.scenario_name == "far"
    assert command.run.seed == 3
    assert command.run.plot_mode == "all"
    assert command.run.plot_output == "combined"
    assert command.run.plot_max_side_px == 1800
