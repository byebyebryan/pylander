from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from skills.lib.orchestration import to_float, to_int


@dataclass(frozen=True)
class BranchGateResult:
    passed: bool
    failures: tuple[str, ...]


def hard_gate(summary: dict[str, Any]) -> BranchGateResult:
    failures: list[str] = []
    if to_int(summary.get("new_global_crashes"), 0) > 0:
        failures.append("new_global_crashes")
    if to_float(summary.get("success_rate_delta"), 0.0) < 0.0:
        failures.append("success_rate_drop")
    if bool(summary.get("notable_global_regression", False)):
        failures.append("notable_global_regression")
    return BranchGateResult(passed=not failures, failures=tuple(failures))


def rank_score(summary: dict[str, Any]) -> float:
    fuel_gain = -to_float(summary.get("fuel_mean_primary_delta"), 0.0)
    compute_avg_penalty = max(0.0, to_float(summary.get("compute_avg_total_delta_ms"), 0.0))
    compute_p99_penalty = max(0.0, to_float(summary.get("compute_p99_total_delta_ms"), 0.0))
    obs_penalty = 0.10 * max(0, to_int(summary.get("observation_regressions"), 0))
    return float(fuel_gain - (0.7 * compute_avg_penalty) - (0.3 * compute_p99_penalty) - obs_penalty)
