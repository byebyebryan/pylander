"""Specialist bot for short vertical descents."""

from __future__ import annotations

from core.bot import Bot
from bots._scenario_common import SpecialistBot, SpecialistConfig


class DropBot(SpecialistBot):
    def __init__(self):
        super().__init__(
            SpecialistConfig(
                name="drop",
                planner_enabled=False,
                align_band=12.0,
                direct_vx_gain=0.09,
                direct_vx_cap=10.0,
                descend_fast=-4.8,
                descend_mid=-3.0,
                descend_slow=-1.4,
                touchdown_vy=-0.75,
                far_altitude=70.0,
                mid_altitude=26.0,
                hold_alt_if_offset=24.0,
                max_tilt=0.52,
                near_tilt=0.13,
            )
        )


def create_bot() -> Bot:
    return DropBot()


__all__ = ["DropBot", "create_bot"]
