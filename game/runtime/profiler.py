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
