from __future__ import annotations

import math
from dataclasses import dataclass

from core.components import Engine, FuelTank, LanderState, Transform
from core.ecs import require_component
from core.maths import Vector2


@dataclass
class RunMetricsTracker:
    start_pos: Vector2
    eval_target_pos: Vector2 | None
    prev_actor_uid: str
    prev_pos: Vector2
    prev_fuel: float
    distance_flown: float = 0.0
    fuel_consumed: float = 0.0
    overdrive_time: float = 0.0
    overdrive_excess: float = 0.0
    landing_count: int = 0
    crash_count: int = 0
    time_to_first_land: float | None = None
    prev_state: str | None = None

    @classmethod
    def from_actor(cls, actor, *, start_pos: Vector2, eval_target_pos: Vector2 | None):
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)
        return cls(
            start_pos=Vector2(start_pos),
            eval_target_pos=Vector2(eval_target_pos) if eval_target_pos is not None else None,
            prev_actor_uid=actor.uid,
            prev_pos=Vector2(trans.pos),
            prev_fuel=float(tank.fuel),
        )

    def update_for_actor(self, actor, *, dt_used: float) -> None:
        trans = require_component(actor, Transform)
        tank = require_component(actor, FuelTank)

        if actor.uid != self.prev_actor_uid:
            self.prev_actor_uid = actor.uid
            self.prev_pos = Vector2(trans.pos)
            self.prev_fuel = float(tank.fuel)
            return

        eng = require_component(actor, Engine)
        step_distance = math.hypot(trans.pos.x - self.prev_pos.x, trans.pos.y - self.prev_pos.y)
        self.distance_flown += step_distance
        self.fuel_consumed += max(0.0, self.prev_fuel - float(tank.fuel))

        throttle = max(0.0, float(eng.thrust_level))
        if throttle > 1.0:
            over = throttle - 1.0
            self.overdrive_time += max(0.0, float(dt_used))
            self.overdrive_excess += over * max(0.0, float(dt_used))

        self.prev_pos = Vector2(trans.pos)
        self.prev_fuel = float(tank.fuel)

    def update_state_counters(self, actor, *, elapsed_time: float) -> None:
        ls = require_component(actor, LanderState)
        state = ls.state
        if state == self.prev_state:
            return
        if state == "landed":
            self.landing_count += 1
            if self.time_to_first_land is None:
                self.time_to_first_land = elapsed_time
        elif state == "crashed":
            self.crash_count += 1
        self.prev_state = state

    def apply_to_result(self, result: dict, *, elapsed_time: float, final_actor) -> None:
        final_trans = require_component(final_actor, Transform)
        final_tank = require_component(final_actor, FuelTank)

        total_t = max(0.0, float(elapsed_time))
        avg_speed = (self.distance_flown / total_t) if total_t > 1e-9 else 0.0
        fuel_per_distance = (
            self.fuel_consumed / self.distance_flown if self.distance_flown > 1e-9 else 0.0
        )
        overdrive_fraction = self.overdrive_time / total_t if total_t > 1e-9 else 0.0

        spawn_to_target_distance = None
        path_efficiency = None
        landing_offset = None
        if self.eval_target_pos is not None:
            spawn_to_target_distance = math.hypot(
                self.eval_target_pos.x - self.start_pos.x,
                self.eval_target_pos.y - self.start_pos.y,
            )
            if result.get("state") == "landed":
                landing_offset = abs(final_trans.pos.x - self.eval_target_pos.x)
                if self.distance_flown > 1e-9:
                    path_efficiency = min(1.0, spawn_to_target_distance / self.distance_flown)

        result.setdefault("distance_flown", self.distance_flown)
        result.setdefault("avg_speed", avg_speed)
        result.setdefault("fuel_consumed", self.fuel_consumed)
        result.setdefault("fuel_remaining", float(final_tank.fuel))
        result.setdefault("fuel_per_distance", fuel_per_distance)
        result.setdefault("overdrive_time", self.overdrive_time)
        result.setdefault("overdrive_fraction", overdrive_fraction)
        result.setdefault("overdrive_excess", self.overdrive_excess)
        result.setdefault("spawn_to_target_distance", spawn_to_target_distance)
        result.setdefault("path_efficiency", path_efficiency)
        result.setdefault("landing_offset", landing_offset)
        result.setdefault("time_to_first_land", self.time_to_first_land)
