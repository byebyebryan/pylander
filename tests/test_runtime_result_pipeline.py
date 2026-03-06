from __future__ import annotations

from core.bot import Bot, BotAction, BotEvalDecision, Sensors
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
        snapshot: dict[str, object] | None = None,
        raise_decision: bool = False,
    ) -> None:
        super().__init__()
        self._decision = decision
        self._snapshot = snapshot
        self._raise_decision = raise_decision

    def update(self, dt: float, sensors: Sensors) -> BotAction:
        _ = dt, sensors
        return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)

    def get_evaluation_decision(self) -> BotEvalDecision | object | None:
        if self._raise_decision:
            raise RuntimeError("boom")
        return self._decision

    def get_evaluation_snapshot(self) -> dict[str, object] | None:
        return self._snapshot


def test_resolve_headless_bot_eval_decision_returns_none_for_non_headless() -> None:
    bot = _Bot(decision=BotEvalDecision(should_end=True))
    assert resolve_headless_bot_eval_decision(headless=False, bot=bot) is None


def test_resolve_headless_bot_eval_decision_ignores_errors_and_invalid_types() -> None:
    assert resolve_headless_bot_eval_decision(headless=True, bot=_Bot(raise_decision=True)) is None
    assert resolve_headless_bot_eval_decision(headless=True, bot=_Bot(decision=object())) is None


def test_merge_bot_snapshots_into_result_prefixes_fields_and_preserves_existing() -> None:
    result = {"zem_phase": "existing"}
    actor_bots = {
        "a": _Bot(snapshot={"kind": "zem_zev", "phase": "setup", "zem_value": 7}),
        "b": _Bot(snapshot={"kind": "other", "ignored": 1}),
    }

    merge_bot_snapshots_into_result(actor_bots=actor_bots, result=result)

    assert result["zem_phase"] == "existing"
    assert result["zem_value"] == 7
    assert "ignored" not in result


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
