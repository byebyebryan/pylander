"""Specialist bot for long horizontal transfer then descent."""

from __future__ import annotations

from core.bot import Bot
from bots._scenario_common import SpecialistBot, SpecialistConfig


class FerryBot(SpecialistBot):
    def __init__(self):
        super().__init__(
            SpecialistConfig(
                name="ferry",
                planner_enabled=True,
                planner_dx_threshold=260.0,
                planner_dist_threshold=360.0,
                planner_replan_interval=0.7,
                planner_pos_error=115.0,
                planner_vel_error=7.5,
                transfer_speed=26.0,
                transfer_vy_limit=5.2,
                transfer_clearance=55.0,
                transfer_complete_dx=70.0,
                transfer_complete_vx=5.2,
                align_band=16.0,
                direct_vx_gain=0.085,
                direct_vx_cap=19.0,
                descend_fast=-6.2,
                descend_mid=-3.8,
                descend_slow=-1.7,
                touchdown_vy=-0.9,
                far_altitude=120.0,
                mid_altitude=36.0,
                hold_alt_if_offset=36.0,
                max_tilt=0.72,
                near_tilt=0.18,
            )
        )


def create_bot() -> Bot:
    return FerryBot()


__all__ = ["FerryBot", "create_bot"]
