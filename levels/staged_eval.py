from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from core.components import FuelTank, Transform
from core.ecs import require_component
from core.maths import Vector2


@dataclass
class ZemTelemetry:
    setup_gate_done: bool = False
    setup_gate_time: float | None = None
    setup_gate_altitude: float | None = None
    setup_gate_projected_dx: float | None = None
    terminal_gate_done: bool = False
    terminal_gate_time: float | None = None
    terminal_gate_altitude: float | None = None
    terminal_gate_projected_dx: float | None = None
    solve_count: float | None = None
    solve_ms_mean: float | None = None
    solve_ms_p90: float | None = None
    fallback_frames: float | None = None


class ZemStageEvalTracker:
    def __init__(self, *, stage_prefix: str, completion_gate_prefix: str) -> None:
        self.stage_prefix = stage_prefix
        self.completion_gate_prefix = completion_gate_prefix
        self.reset()

    @staticmethod
    def to_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    @staticmethod
    def resolve_zem_snapshot(game) -> dict[str, Any] | None:
        actor_bots = getattr(game, "actor_bots", {})
        if not isinstance(actor_bots, dict):
            return None
        for bot in actor_bots.values():
            get_snapshot = getattr(bot, "get_evaluation_snapshot", None)
            if not callable(get_snapshot):
                continue
            try:
                snapshot = get_snapshot()
            except Exception:
                continue
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("kind") or "") == "zem_zev":
                return snapshot
        return None

    def reset(self) -> None:
        self.phase_done = False
        self.phase_time: float | None = None
        self.phase_altitude: float | None = None
        self.phase_projected_dx: float | None = None
        self.phase_distance = 0.0
        self.phase_fuel_consumed = 0.0
        self._prev_pos: Vector2 | None = None
        self._prev_fuel: float | None = None
        self.zem = ZemTelemetry()

    def seed_motion_state(self, actor) -> None:
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)
        self._prev_pos = Vector2(trans.pos)
        self._prev_fuel = float(tank.fuel)

    def update_motion(self, actor) -> None:
        if self.phase_done:
            return
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)

        cur_pos = Vector2(trans.pos)
        cur_fuel = float(tank.fuel)
        if self._prev_pos is not None:
            self.phase_distance += math.hypot(
                cur_pos.x - self._prev_pos.x,
                cur_pos.y - self._prev_pos.y,
            )
        if self._prev_fuel is not None:
            self.phase_fuel_consumed += max(0.0, self._prev_fuel - cur_fuel)
        self._prev_pos = cur_pos
        self._prev_fuel = cur_fuel

    def _pull_zem_telemetry(self, snapshot: dict[str, Any]) -> None:
        self.zem.setup_gate_done = bool(snapshot.get("setup_gate_done"))
        self.zem.setup_gate_time = self.to_optional_float(snapshot.get("setup_gate_time"))
        self.zem.setup_gate_altitude = self.to_optional_float(snapshot.get("setup_gate_altitude"))
        self.zem.setup_gate_projected_dx = self.to_optional_float(
            snapshot.get("setup_gate_projected_dx")
        )
        self.zem.terminal_gate_done = bool(snapshot.get("terminal_gate_done"))
        self.zem.terminal_gate_time = self.to_optional_float(snapshot.get("terminal_gate_time"))
        self.zem.terminal_gate_altitude = self.to_optional_float(
            snapshot.get("terminal_gate_altitude")
        )
        self.zem.terminal_gate_projected_dx = self.to_optional_float(
            snapshot.get("terminal_gate_projected_dx")
        )
        self.zem.solve_count = self.to_optional_float(snapshot.get("solve_count"))
        self.zem.solve_ms_mean = self.to_optional_float(snapshot.get("solve_ms_mean"))
        self.zem.solve_ms_p90 = self.to_optional_float(snapshot.get("solve_ms_p90"))
        self.zem.fallback_frames = self.to_optional_float(snapshot.get("fallback_frames"))

    def capture_snapshot(self, game, actor, target_pos: Vector2, snapshot: dict[str, Any]) -> None:
        self._pull_zem_telemetry(snapshot)

        gate_done_key = f"{self.completion_gate_prefix}_done"
        gate_time_key = f"{self.completion_gate_prefix}_time"
        gate_altitude_key = f"{self.completion_gate_prefix}_altitude"
        gate_projected_dx_key = f"{self.completion_gate_prefix}_projected_dx"

        gate_done = bool(snapshot.get(gate_done_key))
        if self.phase_done or not gate_done:
            return

        trans = require_component(actor, Transform)
        self.phase_done = True
        gate_time = self.to_optional_float(snapshot.get(gate_time_key))
        self.phase_time = gate_time if gate_time is not None else float(getattr(game, "_elapsed_time", 0.0))

        gate_altitude = self.to_optional_float(snapshot.get(gate_altitude_key))
        self.phase_altitude = gate_altitude if gate_altitude is not None else max(
            0.0,
            float(trans.pos.y) - float(target_pos.y),
        )

        self.phase_projected_dx = self.to_optional_float(snapshot.get(gate_projected_dx_key))

    def should_end_focused(self, eval_mode: str) -> bool:
        return eval_mode == "focused" and self.phase_done

    def apply_result(self, result: dict[str, Any], *, eval_mode: str, eval_phase_name: str, actor, target_pos) -> None:
        fuel_per_distance = (
            self.phase_fuel_consumed / self.phase_distance if self.phase_distance > 1e-9 else 0.0
        )

        path_efficiency = None
        start_pos = getattr(actor, "start_pos", None)
        if isinstance(start_pos, Vector2) and isinstance(target_pos, Vector2) and self.phase_distance > 1e-9:
            straight_line = math.hypot(target_pos.x - start_pos.x, target_pos.y - start_pos.y)
            path_efficiency = min(1.0, straight_line / self.phase_distance)

        result[f"{self.stage_prefix}_phase_done"] = self.phase_done
        result[f"{self.stage_prefix}_phase_time"] = self.phase_time
        result[f"{self.stage_prefix}_phase_altitude"] = self.phase_altitude
        result[f"{self.stage_prefix}_phase_projected_dx"] = self.phase_projected_dx
        result[f"{self.stage_prefix}_phase_distance"] = self.phase_distance
        result[f"{self.stage_prefix}_phase_fuel_consumed"] = self.phase_fuel_consumed
        result[f"{self.stage_prefix}_phase_fuel_per_distance"] = fuel_per_distance
        result[f"{self.stage_prefix}_phase_path_efficiency"] = path_efficiency

        result["zem_setup_gate_done"] = self.zem.setup_gate_done
        result["zem_setup_gate_time"] = self.zem.setup_gate_time
        result["zem_setup_gate_altitude"] = self.zem.setup_gate_altitude
        result["zem_setup_gate_projected_dx"] = self.zem.setup_gate_projected_dx
        result["zem_terminal_gate_done"] = self.zem.terminal_gate_done
        result["zem_terminal_gate_time"] = self.zem.terminal_gate_time
        result["zem_terminal_gate_altitude"] = self.zem.terminal_gate_altitude
        result["zem_terminal_gate_projected_dx"] = self.zem.terminal_gate_projected_dx
        result["zem_solve_count"] = self.zem.solve_count
        result["zem_solve_ms_mean"] = self.zem.solve_ms_mean
        result["zem_solve_ms_p90"] = self.zem.solve_ms_p90
        result["zem_fallback_frames"] = self.zem.fallback_frames

        if eval_mode == "focused":
            success = bool(self.phase_done)
            result["eval_phase"] = eval_phase_name
            result["success"] = success
            state = str(result.get("state", "unknown"))
            result["failure_mode"] = "none" if success else state
