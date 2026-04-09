from __future__ import annotations

from collections import deque
from collections.abc import Iterable
import os
from dataclasses import dataclass, field


@dataclass
class BotProfileCounter:
    ticks: int = 0
    passive_build_s: float = 0.0
    bot_update_s: float = 0.0
    total_tick_s: float = 0.0


@dataclass
class BotLoopProfiler:
    enabled: bool
    interval_s: float = 5.0
    next_report_s: float = 5.0
    log_lines: bool = True
    sample_cap: int = 4096
    total: BotProfileCounter = field(default_factory=BotProfileCounter)
    by_bot: dict[str, BotProfileCounter] = field(default_factory=dict)
    total_tick_samples_s: deque[float] = field(default_factory=deque)
    update_tick_samples_s: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        cap = max(1, int(self.sample_cap))
        self.sample_cap = cap
        if self.total_tick_samples_s.maxlen != cap:
            self.total_tick_samples_s = deque(self.total_tick_samples_s, maxlen=cap)
        if self.update_tick_samples_s.maxlen != cap:
            self.update_tick_samples_s = deque(self.update_tick_samples_s, maxlen=cap)

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
    def _record_duration(
        counter: BotProfileCounter, field: str, seconds: float
    ) -> None:
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
        update_s: float,
    ) -> None:
        if not self.enabled:
            return
        total_s = max(0.0, float(passive_s)) + max(0.0, float(update_s))
        counter = self._counter_for_uid(uid)
        self._record_duration(self.total, "total_tick_s", total_s)
        self._record_duration(counter, "total_tick_s", total_s)
        self.total_tick_samples_s.append(total_s)
        self.update_tick_samples_s.append(max(0.0, float(update_s)))

    @staticmethod
    def _ms_per_tick(seconds: float, ticks: int) -> float:
        return 1000.0 * seconds / max(1, ticks)

    @staticmethod
    def _percentile_ms(samples_s: Iterable[float], q: float) -> float:
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
                f"update={self._ms_per_tick(total.bot_update_s, total.ticks):.3f}ms/t "
                f"total={self._ms_per_tick(total.total_tick_s, total.ticks):.3f}ms/t"
            )
        ]

        heavy = sorted(
            self.by_bot.items(),
            key=lambda item: item[1].bot_update_s,
            reverse=True,
        )[:3]
        if heavy:
            bot_parts: list[str] = []
            for uid, counter in heavy:
                bot_parts.append(
                    f"{uid}:u{self._ms_per_tick(counter.bot_update_s, counter.ticks):.3f}"
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
        result["bot_profile_passive_ms_per_tick"] = self._ms_per_tick(
            total.passive_build_s, total.ticks
        )
        result["bot_profile_update_ms_per_tick"] = self._ms_per_tick(
            total.bot_update_s, total.ticks
        )
        result["bot_profile_total_ms_per_tick"] = self._ms_per_tick(
            total.total_tick_s, total.ticks
        )
        result["bot_profile_total_ms_per_tick_p90"] = self._percentile_ms(
            self.total_tick_samples_s, 0.90
        )
        result["bot_profile_total_ms_per_tick_p99"] = self._percentile_ms(
            self.total_tick_samples_s, 0.99
        )
        result["bot_profile_update_ms_per_tick_p90"] = self._percentile_ms(
            self.update_tick_samples_s, 0.90
        )
        result["bot_profile_update_ms_per_tick_p99"] = self._percentile_ms(
            self.update_tick_samples_s, 0.99
        )
