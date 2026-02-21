from __future__ import annotations

import pytest

from core.maths import Range1D
from core.terrain import Target, TargetManager


def _target_func(prev: Target, direction: int) -> Target:
    if direction == 0:
        return Target(x=0.0, y=0.0, size=20.0, info={})
    return Target(
        x=prev.x + direction * 100.0,
        y=0.0,
        size=20.0,
        info={},
    )


def test_target_manager_get_targets_requires_range1d() -> None:
    targets = TargetManager(_target_func)
    span = Range1D.from_center(0.0, 20.0)

    out = targets.get_targets(span)
    assert len(out) >= 1

    with pytest.raises(AttributeError):
        targets.get_targets(0.0)  # type: ignore[arg-type]
