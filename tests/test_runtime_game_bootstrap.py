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


def test_bootstrap_plot_runtime_sets_selector_tag(monkeypatch) -> None:
    class _Plotter:
        def __init__(self, *_args, **_kwargs) -> None:
            self.selector_tag = None

        def set_selector_tag(self, value: str) -> None:
            self.selector_tag = value

    monkeypatch.setattr(game_bootstrap, "Plotter", _Plotter)
    monkeypatch.setattr(game_bootstrap, "level_name_tag", lambda _level: "launch")
    monkeypatch.setattr(game_bootstrap, "level_scenario_tag", lambda _level: "mid")
    monkeypatch.setattr(game_bootstrap, "level_plot_mode", lambda _level: "none")
    monkeypatch.setattr(game_bootstrap, "level_plot_output", lambda _level: "combined")
    monkeypatch.setattr(game_bootstrap, "level_plot_max_side_px", lambda _level: 1234)

    result = game_bootstrap.bootstrap_plot_runtime(
        terrain=object(),
        lander=object(),
        headless=True,
        level=object(),
        seed=7,
    )

    assert result.plotter.selector_tag == "launch_mid_7"
    assert result.events_seen == set()
