from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from game.core.bot import Sensors


def pytest_configure(config: pytest.Config) -> None:
    try:
        import cvxpy  # noqa: F401
    except ImportError:
        config.addinivalue_line(
            "markers", "bot_extra: tests requiring bot extras (cvxpy/pdg)"
        )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    try:
        import cvxpy  # noqa: F401

        cvxpy_available = True
    except ImportError:
        cvxpy_available = False

    if not cvxpy_available:
        skip_bot_extra = pytest.mark.skip(reason="cvxpy not installed (bot extra)")
        for item in items:
            if "bot_extra" in item.keywords:
                item.add_marker(skip_bot_extra)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FlatTerrain:
    """Shared flat-terrain mock for tests."""

    def __call__(self, x: float, lod: int = 0) -> float:
        _ = lod
        return 0.0

    def get_resolution(self, lod: int) -> float:
        _ = lod
        return 1.0


def make_sensors(
    *,
    x: float = 0.0,
    y: float = 0.0,
    altitude: float | None = None,
    vx: float = 0.0,
    vy_up: float = 0.0,
    mass: float = 1000.0,
    thrust_level: float = 0.0,
    state: str = "flying",
) -> Sensors:
    from game.core.bot import Sensors

    return Sensors(
        x=x,
        y=y,
        altitude=max(0.0, y) if altitude is None else altitude,
        terrain_y=0.0,
        terrain_slope=0.0,
        vx=vx,
        vy_up=vy_up,
        angle=0.0,
        ax=0.0,
        ay_up=0.0,
        mass=mass,
        thrust_level=thrust_level,
        fuel=100.0,
        max_fuel=100.0,
        state=state,
        radar_contacts=[],
        proximity=None,
    )
