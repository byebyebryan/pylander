from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

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


@dataclass
class BotProfileCounter:
    ticks: int = 0
    passive_build_s: float = 0.0
    active_build_s: float = 0.0
    query_eval_s: float = 0.0
    bot_update_s: float = 0.0
    query_total: int = 0
    query_raycast: int = 0
    query_terrain_profile: int = 0
    query_ballistic: int = 0


@dataclass
class BotLoopProfiler:
    enabled: bool
    interval_s: float = 5.0
    next_report_s: float = 5.0
    total: BotProfileCounter = field(default_factory=BotProfileCounter)
    by_bot: dict[str, BotProfileCounter] = field(default_factory=dict)

    @staticmethod
    def _env_true(name: str) -> bool:
        value = str(os.getenv(name, "")).strip().lower()
        return value in {"1", "true", "yes", "on"}

    @classmethod
    def from_env(cls, *, headless: bool) -> BotLoopProfiler:
        enabled = headless and cls._env_true("PYLANDER_BOT_PROFILE")
        raw_interval = os.getenv("PYLANDER_BOT_PROFILE_INTERVAL_S", "5.0")
        try:
            interval = max(0.25, float(raw_interval))
        except ValueError:
            interval = 5.0
        return cls(enabled=enabled, interval_s=interval, next_report_s=interval)

    def _counter_for_uid(self, uid: str) -> BotProfileCounter:
        counter = self.by_bot.get(uid)
        if counter is None:
            counter = BotProfileCounter()
            self.by_bot[uid] = counter
        return counter

    @staticmethod
    def _record_duration(counter: BotProfileCounter, field: str, seconds: float) -> None:
        setattr(counter, field, getattr(counter, field) + max(0.0, float(seconds)))

    def record_tick(self, uid: str) -> None:
        if not self.enabled:
            return
        self.total.ticks += 1
        self._counter_for_uid(uid).ticks += 1

    def record_passive_build(self, uid: str, seconds: float) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "passive_build_s", seconds)
        self._record_duration(self._counter_for_uid(uid), "passive_build_s", seconds)

    def record_active_build(self, uid: str, seconds: float) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "active_build_s", seconds)
        self._record_duration(self._counter_for_uid(uid), "active_build_s", seconds)

    def record_query_eval(
        self,
        uid: str,
        seconds: float,
        *,
        query_total: int,
        query_raycast: int,
        query_terrain_profile: int,
        query_ballistic: int,
    ) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "query_eval_s", seconds)
        counter = self._counter_for_uid(uid)
        self._record_duration(counter, "query_eval_s", seconds)

        self.total.query_total += int(query_total)
        self.total.query_raycast += int(query_raycast)
        self.total.query_terrain_profile += int(query_terrain_profile)
        self.total.query_ballistic += int(query_ballistic)

        counter.query_total += int(query_total)
        counter.query_raycast += int(query_raycast)
        counter.query_terrain_profile += int(query_terrain_profile)
        counter.query_ballistic += int(query_ballistic)

    def record_bot_update(self, uid: str, seconds: float) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "bot_update_s", seconds)
        self._record_duration(self._counter_for_uid(uid), "bot_update_s", seconds)

    @staticmethod
    def _ms_per_tick(seconds: float, ticks: int) -> float:
        return 1000.0 * seconds / max(1, ticks)

    def maybe_report_lines(self, elapsed_s: float) -> list[str]:
        if not self.enabled or elapsed_s < self.next_report_s:
            return []
        self.next_report_s = elapsed_s + self.interval_s

        total = self.total
        lines = [
            (
                "bot_prof: "
                f"ticks={total.ticks} "
                f"passive={self._ms_per_tick(total.passive_build_s, total.ticks):.3f}ms/t "
                f"active={self._ms_per_tick(total.active_build_s, total.ticks):.3f}ms/t "
                f"query={self._ms_per_tick(total.query_eval_s, total.ticks):.3f}ms/t "
                f"update={self._ms_per_tick(total.bot_update_s, total.ticks):.3f}ms/t "
                f"q={total.query_total}/{total.query_raycast}/{total.query_terrain_profile}/{total.query_ballistic}"
            )
        ]

        heavy = sorted(
            self.by_bot.items(),
            key=lambda item: item[1].bot_update_s + item[1].query_eval_s,
            reverse=True,
        )[:3]
        if heavy:
            bot_parts: list[str] = []
            for uid, counter in heavy:
                bot_parts.append(
                    f"{uid}:u{self._ms_per_tick(counter.bot_update_s, counter.ticks):.3f}"
                    f"/q{self._ms_per_tick(counter.query_eval_s, counter.ticks):.3f}"
                    f"({counter.ticks})"
                )
            lines.append("bot_prof_top: " + " ".join(bot_parts))
        return lines

    def apply_to_result(self, result: dict) -> None:
        if not self.enabled:
            return
        total = self.total
        result["bot_profile_enabled"] = True
        result["bot_profile_ticks"] = total.ticks
        result["bot_profile_passive_ms_per_tick"] = self._ms_per_tick(total.passive_build_s, total.ticks)
        result["bot_profile_active_ms_per_tick"] = self._ms_per_tick(total.active_build_s, total.ticks)
        result["bot_profile_query_ms_per_tick"] = self._ms_per_tick(total.query_eval_s, total.ticks)
        result["bot_profile_update_ms_per_tick"] = self._ms_per_tick(total.bot_update_s, total.ticks)
        result["bot_profile_query_total"] = total.query_total
        result["bot_profile_query_raycast"] = total.query_raycast
        result["bot_profile_query_terrain_profile"] = total.query_terrain_profile
        result["bot_profile_query_ballistic"] = total.query_ballistic
