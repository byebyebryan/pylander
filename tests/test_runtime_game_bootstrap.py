from __future__ import annotations

from typing import Any, cast

from game.core.level import Level
import game.runtime.game_bootstrap as game_bootstrap


def test_bootstrap_trace_runtime_sets_selector_tag(monkeypatch) -> None:
    class _TraceRecorder:
        def __init__(self, *_args, **kwargs) -> None:
            self.selector_tag = None
            self.detail = kwargs.get("detail")

        def set_selector_tag(self, value: str) -> None:
            self.selector_tag = value

    import tooling.tracepack as tracepack

    monkeypatch.setattr(tracepack, "TraceRecorder", _TraceRecorder)
    monkeypatch.setattr(game_bootstrap, "level_name_tag", lambda _level: "launch")
    monkeypatch.setattr(game_bootstrap, "level_scenario_tag", lambda _level: "mid")
    monkeypatch.setattr(game_bootstrap, "level_trace_enabled", lambda _level: True)
    monkeypatch.setattr(
        game_bootstrap, "level_trace_sample_period_s", lambda _level: 0.25
    )
    monkeypatch.setattr(game_bootstrap, "level_trace_detail", lambda _level: "report")
    level = type("_Level", (Level,), {"setup": lambda self, game, seed: None})()

    result = game_bootstrap.bootstrap_trace_runtime(
        terrain=object(),
        ecs_world=cast(Any, object()),
        actor_bots={},
        active_uid_getter=lambda: "lander",
        headless=True,
        level=level,
        seed=7,
    )

    trace_recorder = cast(Any, result.trace_recorder)
    assert trace_recorder.selector_tag == "launch_mid_7"
    assert trace_recorder.detail == "report"
    assert result.events_seen == set()


def test_bootstrap_trace_runtime_prefers_explicit_selector_tag(monkeypatch) -> None:
    class _TraceRecorder:
        def __init__(self, *_args, **kwargs) -> None:
            self.selector_tag = None
            self.detail = kwargs.get("detail")

        def set_selector_tag(self, value: str) -> None:
            self.selector_tag = value

    import tooling.tracepack as tracepack

    level = type("_Level", (Level,), {"setup": lambda self, game, seed: None})()
    level.set_runtime_identity(trace_selector_tag="plunge_low_half_0#2")
    monkeypatch.setattr(tracepack, "TraceRecorder", _TraceRecorder)
    monkeypatch.setattr(game_bootstrap, "level_name_tag", lambda _level: "launch")
    monkeypatch.setattr(game_bootstrap, "level_scenario_tag", lambda _level: "mid")
    monkeypatch.setattr(game_bootstrap, "level_trace_enabled", lambda _level: True)
    monkeypatch.setattr(
        game_bootstrap, "level_trace_sample_period_s", lambda _level: 0.25
    )
    monkeypatch.setattr(game_bootstrap, "level_trace_detail", lambda _level: "debug")

    result = game_bootstrap.bootstrap_trace_runtime(
        terrain=object(),
        ecs_world=cast(Any, object()),
        actor_bots={},
        active_uid_getter=lambda: "lander",
        headless=True,
        level=level,
        seed=7,
    )

    trace_recorder = cast(Any, result.trace_recorder)
    assert trace_recorder.selector_tag == "plunge_low_half_0#2"
    assert trace_recorder.detail == "debug"
