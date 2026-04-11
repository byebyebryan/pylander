"""Profiler interface owned by game runtime."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable


if TYPE_CHECKING:
    pass


@runtime_checkable
class BotProfiler(Protocol):
    """Protocol for bot loop profiling.

    Runtime code depends on this interface rather than any concrete
    bot-framework profiler implementation.
    """

    enabled: bool

    def record_tick(self, uid: str) -> None:
        """Record a profiling tick for the given actor uid."""
        ...

    def record_passive_build(self, uid: str, seconds: float) -> None:
        """Record passive build time for the given actor uid."""
        ...

    def record_bot_update(self, uid: str, seconds: float) -> None:
        """Record bot update time for the given actor uid."""
        ...

    def record_tick_costs(
        self,
        uid: str,
        *,
        passive_s: float,
        update_s: float,
    ) -> None:
        """Record total tick costs for the given actor uid."""
        ...

    def maybe_report_lines(self, elapsed_s: float) -> list[str]:
        """Return profiling report lines if it's time to report."""
        ...

    def apply_to_result(self, result: dict) -> None:
        """Apply bot profile metrics to the result dict."""
        ...


@dataclass
class BotProfileCounter:
    ticks: int = 0
    passive_build_s: float = 0.0
    bot_update_s: float = 0.0
    total_tick_s: float = 0.0


def bot_profiler_ms_per_tick(seconds: float, ticks: int) -> float:
    """Compute milliseconds per tick from accumulated seconds and tick count."""
    return 1000.0 * seconds / max(1, ticks)


def bot_profiler_percentile_ms(samples_s: Iterable[float], q: float) -> float:
    """Compute percentile of samples in seconds, returning milliseconds."""
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


class NullBotProfiler:
    """No-op profiler for environments where profiling is unavailable or disabled."""

    enabled: bool = False

    def record_tick(self, uid: str) -> None:
        pass

    def record_passive_build(self, uid: str, seconds: float) -> None:
        pass

    def record_bot_update(self, uid: str, seconds: float) -> None:
        pass

    def record_tick_costs(
        self,
        uid: str,
        *,
        passive_s: float,
        update_s: float,
    ) -> None:
        pass

    def maybe_report_lines(self, elapsed_s: float) -> list[str]:
        return []

    def apply_to_result(self, result: dict) -> None:
        pass


class NullTraceRecorder:
    """No-op trace recorder for environments where tracing is unavailable or disabled.

    This provides the minimal interface needed by the session loop without
    requiring imports from tooling.tracepack (which pulls in bot_framework).
    """

    def seed_initial_sample(self) -> None:
        pass

    def set_identity(
        self,
        *,
        level_name: str,
        scenario_name: str | None,
        seed: int | None,
        bot_name: str | None,
        eval_goal: str,
    ) -> None:
        pass

    def set_trace_root_dir(self, path: str | None) -> None:
        pass

    def set_sample_period_s(self, value: float) -> None:
        pass

    def set_trace_detail(self, value: str) -> None:
        pass

    def set_target(
        self,
        *,
        x: float,
        y: float,
        label: str = "target",
        size: float | None = None,
    ) -> None:
        pass

    def update(self, dt: float, *, elapsed_time_s: float) -> None:
        pass

    def finalize(self, *, result: dict, elapsed_time_s: float) -> dict:
        return {}

    def record_controls_map(
        self,
        *,
        elapsed_time_s: float,
        controls_by_uid: dict,
    ) -> None:
        pass

    def record_bot_action(
        self,
        *,
        uid: str,
        elapsed_time_s: float,
        bot_dt_s: float,
        sensors: object,
        action: object,
        passive_s: float,
        update_s: float,
        bot: object,
    ) -> None:
        pass

    def mark_event(
        self,
        *,
        name: str,
        x: float,
        y: float,
        label: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        pass

    def record_eval_decision(self, *, elapsed_time_s: float, decision: object) -> None:
        pass
