from __future__ import annotations

from runtime.loop_timing import LoopTimers
from runtime.physics_steps import (
    PhysicsStepContext,
    sync_actor_masses_to_engine,
    update_physics_steps,
)


class _Actor:
    def __init__(self, uid: str, mass: float) -> None:
        self.uid = uid
        self.mass = mass


class _System:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def update(self, dt: float) -> None:
        self.calls.append(f"{self.name}:{dt:.2f}")


class _StubEngine:
    def __init__(self, *, calls: list[str]) -> None:
        self.calls = calls
        self.masses: list[tuple[str, float]] = []

    def set_mass(self, mass: float, uid: str | None = None) -> None:
        actual_uid = uid if uid is not None else "primary"
        self.masses.append((actual_uid, mass))
        self.calls.append(f"mass:{actual_uid}:{mass:.1f}")

    def step(self, dt: float) -> None:
        self.calls.append(f"engine_step:{dt:.2f}")


def test_sync_actor_masses_to_engine_uses_mass_resolver() -> None:
    calls: list[str] = []
    engine = _StubEngine(calls=calls)
    actors = [_Actor("a", 10.0), _Actor("b", 12.5)]
    cache: dict[str, float] = {}

    sync_actor_masses_to_engine(
        actors=actors,
        engine=engine,
        mass_resolver=lambda actor: actor.mass,
        last_synced_mass_by_uid=cache,
    )

    assert engine.masses == [("a", 10.0), ("b", 12.5)]


def test_update_physics_steps_preserves_system_order_with_engine_enabled() -> None:
    calls: list[str] = []
    actors = [_Actor("a", 10.0), _Actor("b", 12.5)]
    context = PhysicsStepContext(
        actors=actors,
        engine=_StubEngine(calls=calls),
        scripted_control_system=_System("scripted", calls),
        landing_site_motion_system=_System("site_motion", calls),
        landing_site_projection_system=_System("site_projection", calls),
        propulsion_system=_System("propulsion", calls),
        force_application_system=_System("force_apply", calls),
        physics_sync_system=_System("physics_sync", calls),
        contact_system=_System("contact", calls),
        mass_resolver=lambda actor: actor.mass,
    )
    timers = LoopTimers(physics_dt=0.5, bot_dt=1.0, frame_dt=0.5)
    timers.advance_frame(0.5)

    update_physics_steps(timers, context=context)

    assert calls == [
        "scripted:0.50",
        "site_motion:0.50",
        "site_projection:0.50",
        "propulsion:0.50",
        "force_apply:0.50",
        "mass:a:10.0",
        "mass:b:12.5",
        "engine_step:0.50",
        "physics_sync:0.50",
        "contact:0.50",
    ]


def test_update_physics_steps_runs_engine_work_each_step() -> None:
    calls: list[str] = []
    context = PhysicsStepContext(
        actors=[_Actor("a", 10.0)],
        engine=_StubEngine(calls=calls),
        scripted_control_system=_System("scripted", calls),
        landing_site_motion_system=_System("site_motion", calls),
        landing_site_projection_system=_System("site_projection", calls),
        propulsion_system=_System("propulsion", calls),
        force_application_system=_System("force_apply", calls),
        physics_sync_system=_System("physics_sync", calls),
        contact_system=_System("contact", calls),
        mass_resolver=lambda actor: actor.mass,
    )
    timers = LoopTimers(physics_dt=0.25, bot_dt=1.0, frame_dt=0.25)
    timers.advance_frame(0.25)

    update_physics_steps(timers, context=context)

    assert calls == [
        "scripted:0.25",
        "site_motion:0.25",
        "site_projection:0.25",
        "propulsion:0.25",
        "force_apply:0.25",
        "mass:a:10.0",
        "engine_step:0.25",
        "physics_sync:0.25",
        "contact:0.25",
    ]


def test_sync_actor_masses_to_engine_skips_unchanged_masses() -> None:
    calls: list[str] = []
    engine = _StubEngine(calls=calls)
    actors = [_Actor("a", 10.0), _Actor("b", 12.5)]
    cache: dict[str, float] = {}

    sync_actor_masses_to_engine(
        actors=actors,
        engine=engine,
        mass_resolver=lambda actor: actor.mass,
        last_synced_mass_by_uid=cache,
    )

    assert engine.masses == [("a", 10.0), ("b", 12.5)]
    engine.masses.clear()
    calls.clear()

    sync_actor_masses_to_engine(
        actors=actors,
        engine=engine,
        mass_resolver=lambda actor: actor.mass,
        last_synced_mass_by_uid=cache,
    )

    assert engine.masses == []
