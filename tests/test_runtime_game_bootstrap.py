from __future__ import annotations

import runtime.game_bootstrap as game_bootstrap


class _Systems:
    def __init__(self) -> None:
        self.control_routing = object()
        self.state_transition = object()
        self.scripted_control = object()
        self.landing_site_motion = object()
        self.landing_site_projection = object()
        self.refuel = object()
        self.propulsion = object()
        self.force_application = object()
        self.physics_sync = object()
        self.contact = object()
        self.sensor_update = object()


def test_bind_system_aliases_sets_expected_attributes() -> None:
    owner = type("_Owner", (), {})()
    systems = _Systems()

    game_bootstrap.bind_system_aliases(owner, systems)

    assert owner.control_routing_system is systems.control_routing
    assert owner.state_transition_system is systems.state_transition
    assert owner.scripted_control_system is systems.scripted_control
    assert owner.landing_site_motion_system is systems.landing_site_motion
    assert owner.landing_site_projection_system is systems.landing_site_projection
    assert owner.refuel_system is systems.refuel
    assert owner.propulsion_system is systems.propulsion
    assert owner.force_application_system is systems.force_application
    assert owner.physics_sync_system is systems.physics_sync
    assert owner.contact_system is systems.contact
    assert owner.sensor_update_system is systems.sensor_update


def test_bootstrap_trace_runtime_sets_selector_tag(monkeypatch) -> None:
    class _TraceRecorder:
        def __init__(self, *_args, **kwargs) -> None:
            self.selector_tag = None
            self.detail = kwargs.get("detail")

        def set_selector_tag(self, value: str) -> None:
            self.selector_tag = value

    monkeypatch.setattr(game_bootstrap, "TraceRecorder", _TraceRecorder)
    monkeypatch.setattr(game_bootstrap, "level_name_tag", lambda _level: "launch")
    monkeypatch.setattr(game_bootstrap, "level_scenario_tag", lambda _level: "mid")
    monkeypatch.setattr(game_bootstrap, "level_trace_enabled", lambda _level: True)
    monkeypatch.setattr(game_bootstrap, "level_trace_sample_period_s", lambda _level: 0.25)
    monkeypatch.setattr(game_bootstrap, "level_trace_detail", lambda _level: "report")

    result = game_bootstrap.bootstrap_trace_runtime(
        terrain=object(),
        ecs_world=object(),
        actor_bots={},
        active_uid_getter=lambda: "lander",
        headless=True,
        level=object(),
        seed=7,
    )

    assert result.trace_recorder.selector_tag == "launch_mid_7"
    assert result.trace_recorder.detail == "report"
    assert result.events_seen == set()


def test_bootstrap_trace_runtime_prefers_explicit_selector_tag(monkeypatch) -> None:
    class _TraceRecorder:
        def __init__(self, *_args, **kwargs) -> None:
            self.selector_tag = None
            self.detail = kwargs.get("detail")

        def set_selector_tag(self, value: str) -> None:
            self.selector_tag = value

    level = type("_Level", (), {"trace_selector_tag": "plunge_low_half_0#2"})()
    monkeypatch.setattr(game_bootstrap, "TraceRecorder", _TraceRecorder)
    monkeypatch.setattr(game_bootstrap, "level_name_tag", lambda _level: "launch")
    monkeypatch.setattr(game_bootstrap, "level_scenario_tag", lambda _level: "mid")
    monkeypatch.setattr(game_bootstrap, "level_trace_enabled", lambda _level: True)
    monkeypatch.setattr(game_bootstrap, "level_trace_sample_period_s", lambda _level: 0.25)
    monkeypatch.setattr(game_bootstrap, "level_trace_detail", lambda _level: "debug")

    result = game_bootstrap.bootstrap_trace_runtime(
        terrain=object(),
        ecs_world=object(),
        actor_bots={},
        active_uid_getter=lambda: "lander",
        headless=True,
        level=level,
        seed=7,
    )

    assert result.trace_recorder.selector_tag == "plunge_low_half_0#2"
    assert result.trace_recorder.detail == "debug"
