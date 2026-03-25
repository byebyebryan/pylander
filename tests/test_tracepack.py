from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from matplotlib.axes import Axes

from core.bot import BotAction, BotEvalDecision
from core.components import Engine, FuelTank, LanderState, PhysicsState, Transform
from core.ecs import Entity, World
from core.maths import Vector2
from utils import tracepack


def test_write_preview_png_draws_actual_and_reference_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    original_plot = Axes.plot

    def _recording_plot(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"args": args, "kwargs": dict(kwargs)})
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", _recording_plot)

    out_path = tmp_path / "preview.png"
    tracepack._write_preview_png(
        {
            "terrain": {"xs": [-50.0, 0.0, 50.0], "ys": [0.0, 0.0, 0.0]},
            "samples": {"x": [-20.0, -5.0, 4.0], "y": [48.0, 22.0, 1.5]},
            "reference_curve": {"xs": [-20.0, -8.0, 0.0], "ys": [48.0, 30.0, 0.0]},
            "bounds": {"min_x": -60.0, "max_x": 60.0, "lower_y": -5.0, "upper_y": 60.0},
            "target": {"x": 0.0, "y": 0.0, "size": 110.0},
            "events": [{"name": "crash", "x": 4.0, "y": 1.5}],
        },
        out_path=out_path,
    )

    assert out_path.exists()
    assert any(
        cast(dict[str, Any], call["kwargs"]).get("color") == "#0057d8"
        and cast(dict[str, Any], call["kwargs"]).get("linewidth") == 2.0
        for call in calls
    )
    assert any(
        cast(dict[str, Any], call["kwargs"]).get("color") == "#ff8a00"
        and cast(dict[str, Any], call["kwargs"]).get("linestyle") == "--"
        for call in calls
    )


def test_derive_plot_payload_uses_boost_cutoff_for_ballistic_curve(
    monkeypatch,
) -> None:
    observed: dict[str, float] = {}

    def _fake_ballistic_curve_from_state(
        *, x, y, vx, vy_up, target_x, target_y, gravity_mag=9.8
    ):  # type: ignore[no-untyped-def]
        observed.update(
            {
                "x": float(x),
                "y": float(y),
                "vx": float(vx),
                "vy_up": float(vy_up),
                "target_x": float(target_x),
                "target_y": float(target_y),
            }
        )
        return [float(x), float(target_x)], [float(y), float(target_y)], True

    monkeypatch.setattr(
        tracepack, "_ballistic_curve_from_state", _fake_ballistic_curve_from_state
    )

    class _Terrain:
        def __call__(self, x: float, lod: int = 0) -> float:
            _ = (x, lod)
            return 0.0

        def get_resolution(self, lod: int = 0) -> float:
            _ = lod
            return 4.0

    payload = tracepack._derive_plot_payload(
        _Terrain(),
        samples=[
            (0.0, 4.0, 10.0, 1.0, 0.0, 0.0, 0.0, 12.0),
            (40.0, 30.0, 18.0, 0.6, 0.0, 2.0, 14.0, 8.0),
            (120.0, 4.0, 24.0, 0.0, 0.0, 10.0, 0.0, 0.0),
        ],
        events=[
            {
                "name": "boost_cutoff",
                "x": 40.0,
                "y": 30.0,
                "vx": 14.0,
                "vy_up": 8.0,
                "time_s": 2.0,
            }
        ],
        target={"x": 150.0, "y": 0.0},
    )

    assert payload is not None
    assert observed == {
        "x": 40.0,
        "y": 30.0,
        "vx": 14.0,
        "vy_up": 8.0,
        "target_x": 150.0,
        "target_y": 0.0,
    }
    assert payload["ballistic_curve"]["source"] == "boost_cutoff"
    assert payload["ballistic_curve"]["xs"] == [40.0, 150.0]


def test_trace_recorder_samples_current_frame_time_without_backdating(
    tmp_path: Path,
) -> None:
    class _Terrain:
        def __call__(self, _x: float, lod: int = 0) -> float:
            _ = lod
            return 0.0

        def get_resolution(self, lod: int = 0) -> float:
            _ = lod
            return 4.0

    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(1.0, 2.0)))
    world = World()
    world.add_entity(actor)
    recorder = tracepack.TraceRecorder(
        enabled=True,
        terrain=_Terrain(),
        ecs_world=world,
        actor_bots={},
        active_uid_getter=lambda: "lander",
        outputs_root=tmp_path,
        sample_period_s=0.25,
    )

    recorder.seed_initial_sample()
    recorder.update(0.30, elapsed_time_s=0.30)
    recorder.update(0.60, elapsed_time_s=0.90)

    trace_meta = recorder.finalize(result={"state": "flying"}, elapsed_time_s=0.90)
    trace_payload = json.loads(
        Path(str(trace_meta["trace_path"])).read_text(encoding="utf-8")
    )
    snapshots = trace_payload["snapshots"]
    assert [round(float(item["elapsed_time_s"]), 3) for item in snapshots[:3]] == [
        0.0,
        0.3,
        0.9,
    ]


def _make_trace_recorder(
    tmp_path: Path, *, detail: str
) -> tuple[tracepack.TraceRecorder, Entity]:
    class _Terrain:
        def __call__(self, _x: float, lod: int = 0) -> float:
            _ = lod
            return 0.0

        def get_resolution(self, lod: int = 0) -> float:
            _ = lod
            return 4.0

    actor = Entity("lander")
    actor.add_component(Transform(pos=Vector2(1.0, 4.0)))
    actor.add_component(PhysicsState())
    actor.add_component(Engine())
    actor.add_component(FuelTank())
    actor.add_component(LanderState(state=cast(Any, "landed")))
    world = World()
    world.add_entity(actor)
    recorder = tracepack.TraceRecorder(
        enabled=True,
        terrain=_Terrain(),
        ecs_world=world,
        actor_bots={},
        active_uid_getter=lambda: "lander",
        outputs_root=tmp_path,
        sample_period_s=0.25,
        detail=detail,
    )
    recorder.seed_initial_sample()
    return recorder, actor


def test_trace_recorder_report_mode_omits_control_log_and_entity_catalog(
    tmp_path: Path,
) -> None:
    recorder, actor = _make_trace_recorder(tmp_path, detail="report")
    actor.get_component(Transform).pos = Vector2(10.0, 4.0)  # type: ignore[union-attr]
    recorder.update(0.30, elapsed_time_s=0.30)
    recorder.record_controls_map(
        elapsed_time_s=0.30,
        controls_by_uid={"lander": (0.7, 0.1, False)},
    )
    recorder.mark_event(name="boost_cutoff", x=5.0, y=9.0, metadata={"time_s": 0.30})
    recorder.record_eval_decision(
        elapsed_time_s=0.30,
        decision=BotEvalDecision(should_end=True, success=True, end_reason="done"),
    )

    trace_meta = recorder.finalize(
        result={"state": "landed", "success": True}, elapsed_time_s=0.30
    )
    trace_path = Path(str(trace_meta["trace_path"]))
    trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace_meta["trace_detail"] == "report"
    assert trace_meta["trace_control_log_count"] == 0
    assert trace_payload["trace_detail"] == "report"
    assert "control_log" not in trace_payload
    assert "entity_catalog" not in trace_payload
    assert trace_path.read_text(encoding="utf-8").count("\n") == 0


def test_trace_recorder_persists_identity_and_sanitized_selector_tag(
    tmp_path: Path,
) -> None:
    recorder, _actor = _make_trace_recorder(tmp_path, detail="report")
    recorder.set_identity(
        level_name="boost",
        scenario_name="flat:mid:half",
        seed=7,
        bot_name="pdg",
        eval_goal="landing",
    )
    recorder.set_selector_tag("boost flat:mid:half#7")

    trace_meta = recorder.finalize(
        result={"state": "landed", "success": True}, elapsed_time_s=0.0
    )
    trace_payload = json.loads(
        Path(str(trace_meta["trace_path"])).read_text(encoding="utf-8")
    )

    assert trace_payload["selector_tag"] == "boost_flat_mid_half_7"
    assert (
        Path(str(trace_meta["trace_path"])).name == "boost_flat_mid_half_7.trace.json"
    )
    assert trace_payload["identity"] == {
        "level": "boost",
        "scenario": "flat:mid:half",
        "seed": 7,
        "bot": "pdg",
        "eval_goal": "landing",
    }


def test_trace_recorder_replay_mode_keeps_lean_control_log(tmp_path: Path) -> None:
    recorder, _actor = _make_trace_recorder(tmp_path, detail="replay")
    sensors = SimpleNamespace(
        x=0.0,
        y=4.0,
        altitude=4.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=100.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
    )
    recorder.record_bot_action(
        uid="lander",
        elapsed_time_s=0.10,
        bot_dt_s=1 / 60,
        sensors=sensors,
        action=BotAction(target_thrust=0.3, target_angle=0.0, refuel=False),
        passive_s=0.001,
        update_s=0.002,
        bot=object(),  # type: ignore[arg-type]
    )
    recorder.record_controls_map(
        elapsed_time_s=0.10,
        controls_by_uid={"lander": (0.3, 0.0, False)},
    )
    recorder.mark_event(name="boost_cutoff", x=5.0, y=9.0, metadata={"time_s": 0.10})
    recorder.record_eval_decision(
        elapsed_time_s=0.30,
        decision=BotEvalDecision(should_end=True, success=True, end_reason="done"),
    )

    trace_meta = recorder.finalize(
        result={"state": "landed", "success": True}, elapsed_time_s=0.30
    )
    trace_payload = json.loads(
        Path(str(trace_meta["trace_path"])).read_text(encoding="utf-8")
    )
    kinds = [item["kind"] for item in trace_payload["control_log"]]

    assert trace_meta["trace_detail"] == "replay"
    assert "entity_catalog" in trace_payload
    assert "bot_action" not in kinds
    assert "routed_controls" in kinds
    assert "event" in kinds
    assert "eval_decision" in kinds
    assert "outcome" in kinds


def test_trace_recorder_debug_mode_keeps_verbose_bot_action_log(tmp_path: Path) -> None:
    recorder, _actor = _make_trace_recorder(tmp_path, detail="debug")
    sensors = SimpleNamespace(
        x=0.0,
        y=4.0,
        altitude=4.0,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=0.0,
        vy_up=0.0,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=100.0,
        thrust_level=0.0,
        fuel=100.0,
        state="flying",
    )
    recorder.record_bot_action(
        uid="lander",
        elapsed_time_s=0.10,
        bot_dt_s=1 / 60,
        sensors=sensors,
        action=BotAction(
            target_thrust=0.3, target_angle=0.0, refuel=False, status="ok"
        ),
        passive_s=0.001,
        update_s=0.002,
        bot=object(),  # type: ignore[arg-type]
    )
    recorder.record_controls_map(
        elapsed_time_s=0.10,
        controls_by_uid={"lander": (0.3, 0.0, False)},
    )

    trace_meta = recorder.finalize(
        result={"state": "landed", "success": True}, elapsed_time_s=0.30
    )
    trace_payload = json.loads(
        Path(str(trace_meta["trace_path"])).read_text(encoding="utf-8")
    )
    kinds = [item["kind"] for item in trace_payload["control_log"]]

    assert trace_meta["trace_detail"] == "debug"
    assert "bot_action" in kinds
