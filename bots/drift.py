"""Specialist bot for medium horizontal transfer then descent."""

from __future__ import annotations

from core.bot import Bot
from bots._scenario_common import SpecialistBot, SpecialistConfig


class DriftBot(SpecialistBot):
    def __init__(self):
        super().__init__(
            SpecialistConfig(
                name="drift",
                planner_enabled=True,
                planner_dx_threshold=150.0,
                planner_dist_threshold=220.0,
                planner_replan_interval=0.8,
                planner_pos_error=100.0,
                planner_vel_error=6.0,
                transfer_speed=19.0,
                transfer_vy_limit=3.8,
                transfer_clearance=30.0,
                transfer_complete_dx=55.0,
                transfer_complete_vx=4.0,
                align_band=14.0,
                direct_vx_gain=0.09,
                direct_vx_cap=15.0,
                descend_fast=-4.8,
                descend_mid=-3.2,
                descend_slow=-1.6,
                touchdown_vy=-0.8,
                far_altitude=80.0,
                mid_altitude=30.0,
                hold_alt_if_offset=32.0,
                max_tilt=0.62,
                near_tilt=0.16,
            )
        )


def create_bot() -> Bot:
    return DriftBot()


__all__ = ["DriftBot", "create_bot"]
