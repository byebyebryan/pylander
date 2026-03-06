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
    total_tick_s: float = 0.0
    query_total: int = 0
    query_raycast: int = 0
    query_terrain_profile: int = 0


@dataclass
class BotLoopProfiler:
    enabled: bool
    interval_s: float = 5.0
    next_report_s: float = 5.0
    log_lines: bool = True
    total: BotProfileCounter = field(default_factory=BotProfileCounter)
    by_bot: dict[str, BotProfileCounter] = field(default_factory=dict)
    total_tick_samples_s: list[float] = field(default_factory=list)
    query_tick_samples_s: list[float] = field(default_factory=list)
    update_tick_samples_s: list[float] = field(default_factory=list)

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
        log_lines = not cls._env_true("PYLANDER_BOT_PROFILE_NO_LOG_LINES")
        return cls(
            enabled=enabled,
            interval_s=interval,
            next_report_s=interval,
            log_lines=log_lines,
        )

    @classmethod
    def from_settings(
        cls,
        *,
        headless: bool,
        enabled: bool | None = None,
        interval_s: float | None = None,
        log_lines: bool | None = None,
    ) -> BotLoopProfiler:
        profiler = cls.from_env(headless=headless)
        if enabled is not None:
            profiler.enabled = bool(enabled) and headless
        if interval_s is not None:
            profiler.interval_s = max(0.25, float(interval_s))
            profiler.next_report_s = profiler.interval_s
        if log_lines is not None:
            profiler.log_lines = bool(log_lines)
        return profiler

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
    ) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "query_eval_s", seconds)
        counter = self._counter_for_uid(uid)
        self._record_duration(counter, "query_eval_s", seconds)

        self.total.query_total += int(query_total)
        self.total.query_raycast += int(query_raycast)
        self.total.query_terrain_profile += int(query_terrain_profile)

        counter.query_total += int(query_total)
        counter.query_raycast += int(query_raycast)
        counter.query_terrain_profile += int(query_terrain_profile)

    def record_bot_update(self, uid: str, seconds: float) -> None:
        if not self.enabled:
            return
        self._record_duration(self.total, "bot_update_s", seconds)
        self._record_duration(self._counter_for_uid(uid), "bot_update_s", seconds)

    def record_tick_costs(
        self,
        uid: str,
        *,
        passive_s: float,
        active_s: float,
        query_s: float,
        update_s: float,
    ) -> None:
        if not self.enabled:
            return
        total_s = (
            max(0.0, float(passive_s))
            + max(0.0, float(active_s))
            + max(0.0, float(query_s))
            + max(0.0, float(update_s))
        )
        counter = self._counter_for_uid(uid)
        self._record_duration(self.total, "total_tick_s", total_s)
        self._record_duration(counter, "total_tick_s", total_s)
        self.total_tick_samples_s.append(total_s)
        self.query_tick_samples_s.append(max(0.0, float(query_s)))
        self.update_tick_samples_s.append(max(0.0, float(update_s)))

    @staticmethod
    def _ms_per_tick(seconds: float, ticks: int) -> float:
        return 1000.0 * seconds / max(1, ticks)

    @staticmethod
    def _percentile_ms(samples_s: list[float], q: float) -> float:
        if not samples_s:
            return 0.0
        vals = sorted(float(max(0.0, x)) for x in samples_s)
        if len(vals) == 1:
            return 1000.0 * vals[0]
        q_clamped = max(0.0, min(1.0, float(q)))
        idx = q_clamped * (len(vals) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(vals) - 1)
        frac = idx - lo
        v = vals[lo] * (1.0 - frac) + vals[hi] * frac
        return 1000.0 * v

    def maybe_report_lines(self, elapsed_s: float) -> list[str]:
        if not self.enabled or not self.log_lines or elapsed_s < self.next_report_s:
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
                f"total={self._ms_per_tick(total.total_tick_s, total.ticks):.3f}ms/t "
                f"q={total.query_total}/{total.query_raycast}/{total.query_terrain_profile}"
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
        result["bot_profile_total_ms_per_tick"] = self._ms_per_tick(total.total_tick_s, total.ticks)
        result["bot_profile_total_ms_per_tick_p90"] = self._percentile_ms(self.total_tick_samples_s, 0.90)
        result["bot_profile_total_ms_per_tick_p99"] = self._percentile_ms(self.total_tick_samples_s, 0.99)
        result["bot_profile_query_ms_per_tick_p90"] = self._percentile_ms(self.query_tick_samples_s, 0.90)
        result["bot_profile_query_ms_per_tick_p99"] = self._percentile_ms(self.query_tick_samples_s, 0.99)
        result["bot_profile_update_ms_per_tick_p90"] = self._percentile_ms(self.update_tick_samples_s, 0.90)
        result["bot_profile_update_ms_per_tick_p99"] = self._percentile_ms(self.update_tick_samples_s, 0.99)
        result["bot_profile_query_total"] = total.query_total
        result["bot_profile_query_raycast"] = total.query_raycast
        result["bot_profile_query_terrain_profile"] = total.query_terrain_profile
