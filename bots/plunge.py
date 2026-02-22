"""Specialist bot for high-altitude vertical descents."""

from __future__ import annotations

from core.bot import Bot
from bots._scenario_common import SpecialistBot, SpecialistConfig


class PlungeBot(SpecialistBot):
    def __init__(self):
        super().__init__(
            SpecialistConfig(
                name="plunge",
                planner_enabled=False,
                align_band=13.0,
                direct_vx_gain=0.085,
                direct_vx_cap=12.0,
                descend_fast=-7.0,
                descend_mid=-4.6,
                descend_slow=-1.8,
                touchdown_vy=-0.9,
                far_altitude=150.0,
                mid_altitude=42.0,
                hold_alt_if_offset=34.0,
                k_vy=0.16,
                max_tilt=0.58,
                near_tilt=0.15,
            )
        )


def create_bot() -> Bot:
    return PlungeBot()


__all__ = ["PlungeBot", "create_bot"]
