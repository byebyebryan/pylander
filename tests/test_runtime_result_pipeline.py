from __future__ import annotations

from core.bot import Bot, BotAction, BotEvalDecision, FlightPhaseSnapshot, Sensors, SetupGateMetrics
from runtime.result_pipeline import (
    apply_bot_eval_to_result,
    merge_bot_snapshots_into_result,
    resolve_headless_bot_eval_decision,
)


class _Bot(Bot):
    def __init__(
        self,
        *,
        decision: BotEvalDecision | object | None = None,
        telemetry: dict[str, object] | None = None,
        phase_snapshot: FlightPhaseSnapshot | None = None,
        raise_decision: bool = False,
    ) -> None:
        super().__init__()
        self._bot_name = "pdg"
        self._decision = decision
        self._telemetry = telemetry
        self._phase_snapshot = phase_snapshot
        self._raise_decision = raise_decision

    def update(self, dt: float, sensors: Sensors) -> BotAction:
        _ = dt, sensors
        return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    def get_evaluation_decision(self) -> BotEvalDecision | object | None:
        if self._raise_decision:
            raise RuntimeError("boom")
        return self._decision

    def get_bot_telemetry(self) -> dict[str, object]:
        return dict(self._telemetry or {})

    def get_flight_phase_snapshot(self) -> FlightPhaseSnapshot | None:
        return self._phase_snapshot


def test_resolve_headless_bot_eval_decision_returns_none_for_non_headless() -> None:
    bot = _Bot(decision=BotEvalDecision(should_end=True))
    assert resolve_headless_bot_eval_decision(headless=False, bot=bot) is None


def test_resolve_headless_bot_eval_decision_ignores_errors_and_invalid_types() -> None:
    assert resolve_headless_bot_eval_decision(headless=True, bot=_Bot(raise_decision=True)) is None
    assert resolve_headless_bot_eval_decision(headless=True, bot=_Bot(decision=object())) is None


def test_merge_bot_snapshots_into_result_prefixes_fields_and_preserves_existing() -> None:
    result = {"bot_pdg_value": "existing", "setup_gate_done": "existing"}
    actor_bots = {
        "a": _Bot(
            telemetry={"value": 7, "solve_count": 9, "bot_other_done": True},
            phase_snapshot=FlightPhaseSnapshot(
                phase="coast",
                milestones=("setup_gate",),
                setup_gate=SetupGateMetrics(
                    time_s=4.0,
                    altitude=90.0,
                    projected_apex_over_target=25.0,
                    has_target_y_solution=True,
                    projected_impact_dx=7.5,
                    projected_impact_angle_deg=61.0,
                    burn_duration_s=4.0,
                    burn_fuel_used=12.0,
                    burn_avg_thrust_level=0.82,
                ),
            ),
        ),
        "b": _Bot(telemetry={"ignored": 1}),
    }

    merge_bot_snapshots_into_result(actor_bots=actor_bots, result=result)

    assert result["bot_pdg_value"] == "existing"
    assert result["bot_pdg_solve_count"] == 9
    assert result["bot_pdg_ignored"] == 1
    assert result["setup_gate_done"] == "existing"
    assert result["setup_gate_time"] == 4.0
    assert result["setup_gate_projected_dx"] == 7.5
    assert result["setup_gate_projected_impact_angle_deg"] == 61.0
    assert result["setup_gate_burn_avg_thrust_level"] == 0.82
    assert result["bot_pdg_value"] == "existing"
    assert result["bot_other_done"] is True


def test_apply_bot_eval_to_result_keeps_landing_passthrough_semantics() -> None:
    result = {"success": False, "failure_mode": "crashed"}
    decision = BotEvalDecision(
        should_end=True,
        success=True,
        failure_mode="none",
        end_reason="goal_reached",
        metrics={"metric_x": 3},
    )

    apply_bot_eval_to_result(
        result=result,
        eval_goal="landing",
        decision=decision,
    )

    assert result["eval_goal"] == "landing"
    assert result["eval_early_end"] is True
    assert result["eval_end_reason"] == "goal_reached"
    assert result["metric_x"] == 3
    assert result["success"] is True
    assert result["failure_mode"] == "none"


def test_apply_bot_eval_to_result_marks_non_landing_goal_not_reached() -> None:
    result: dict[str, object] = {}

    apply_bot_eval_to_result(
        result=result,
        eval_goal="setup",
        decision=None,
    )

    assert result["eval_goal"] == "setup"
    assert result["eval_early_end"] is False
    assert result["success"] is False
    assert result["failure_mode"] == "goal_not_reached"
    assert result["eval_end_reason"] == "goal_not_reached"


def test_apply_bot_eval_to_result_copies_setup_gate_metrics_into_setup_goal() -> None:
    result: dict[str, object] = {
        "setup_gate_done": True,
        "setup_gate_time": 5.5,
        "setup_gate_altitude": 140.0,
        "setup_gate_projected_apex_y": 220.0,
        "setup_gate_projected_apex_over_target": 35.0,
        "setup_gate_has_target_y_solution": True,
        "setup_gate_projected_dx": 6.0,
        "setup_gate_projected_impact_angle_deg": 58.0,
        "setup_gate_burn_fuel_used": 19.0,
        "setup_gate_burn_avg_thrust_level": 0.87,
    }
    decision = BotEvalDecision(should_end=True, success=True, failure_mode="none")

    apply_bot_eval_to_result(
        result=result,
        eval_goal="setup",
        decision=decision,
    )

    assert result["setup_goal_done"] is True
    assert result["setup_goal_time"] == 5.5
    assert result["setup_goal_altitude"] == 140.0
    assert result["setup_goal_projected_apex_over_target"] == 35.0
    assert result["setup_goal_projected_dx"] == 6.0
    assert result["setup_goal_projected_impact_angle_deg"] == 58.0
    assert result["setup_goal_fuel_consumed"] == 19.0
    assert result["setup_goal_burn_avg_thrust_level"] == 0.87


def test_apply_bot_eval_to_result_preserves_setup_gate_metrics_on_failure() -> None:
    result: dict[str, object] = {
        "setup_gate_done": True,
        "setup_gate_time": 4.0,
        "setup_gate_projected_dx": 120.0,
    }
    decision = BotEvalDecision(
        should_end=True,
        success=False,
        failure_mode="setup_quality_failed",
        end_reason="setup_quality_failed",
        metrics={"setup_quality_verdict": "dx"},
    )

    apply_bot_eval_to_result(
        result=result,
        eval_goal="setup",
        decision=decision,
    )

    assert result["eval_early_end"] is True
    assert result["failure_mode"] == "setup_quality_failed"
    assert result["eval_end_reason"] == "setup_quality_failed"
    assert result["setup_quality_verdict"] == "dx"
    assert result["setup_goal_done"] is True
    assert result["setup_goal_time"] == 4.0
    assert result["setup_goal_projected_dx"] == 120.0
