"""Minimal demo bot for the batched query plan/act interface."""

from __future__ import annotations

import math

from core.bot import BotAction, PassiveSensors, QueryBot
from core.bot_queries import (
    BallisticResult,
    BotQuery,
    BotQueryBallistic,
    BotQueryRaycast,
    BotQueryResults,
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class QueryDemoBot(QueryBot):
    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _pick_target(passive: PassiveSensors):
        contacts = list(passive.radar_contacts or [])
        if not contacts:
            return None
        return min(contacts, key=lambda c: float(c.distance))

    def plan(self, dt: float, passive: PassiveSensors) -> list[BotQuery]:
        _ = dt
        queries: list[BotQuery] = [
            BotQueryBallistic(
                id="ballistic",
                x=float(passive.x),
                y=float(passive.y),
                vx=float(passive.vx),
                vy_up=float(passive.vy_up),
                max_distance=6000.0,
                segment_length=20.0,
                max_points=192,
                lod=0,
                clearance=0.0,
            )
        ]

        target = self._pick_target(passive)
        if target is not None:
            dx = float(target.x) - float(passive.x)
            dy = float(target.y) - float(passive.y)
            ray_angle = math.atan2(dy, dx)
            ray_range = max(200.0, math.hypot(dx, dy) + 100.0)
            queries.append(
                BotQueryRaycast(
                    id="target_ray",
                    dir_angle=ray_angle,
                    max_range=ray_range,
                )
            )
        return queries

    def act(
        self,
        dt: float,
        passive: PassiveSensors,
        results: BotQueryResults,
    ) -> BotAction:
        _ = dt
        if passive.state == "landed":
            self.status = "query_demo:landed"
            return BotAction(target_thrust=0.0, target_angle=0.0, refuel=False)
        if passive.state in {"crashed", "out_of_fuel"}:
            self.status = f"query_demo:{passive.state}"
            return BotAction(target_thrust=0.0, target_angle=float(passive.angle), refuel=False)

        target = self._pick_target(passive)
        dx = 0.0
        if target is not None:
            dx = float(target.x) - float(passive.x)
        angle_cmd = _clamp(0.004 * dx, -0.35, 0.35)

        thrust = 0.0
        tgo = None
        ballistic = results.get("ballistic")
        if isinstance(ballistic, BallisticResult) and ballistic.hit:
            if ballistic.hit_time is not None:
                tgo = float(ballistic.hit_time)
            if tgo is not None and tgo < 2.0:
                thrust = 0.95
            elif float(passive.vy_up) < -8.0:
                thrust = 0.85
            elif float(passive.vy_up) < -4.0:
                thrust = 0.60
            else:
                thrust = 0.25
        else:
            if float(passive.vy_up) < -5.0:
                thrust = 0.75
            elif float(passive.vy_up) < -2.0:
                thrust = 0.45

        max_thrust = 1.0
        min_thrust = 0.0
        if self.vehicle_info is not None:
            max_thrust = max(0.0, float(self.vehicle_info.max_thrust))
            min_thrust = max(0.0, min(float(self.vehicle_info.min_thrust), max_thrust))
        thrust = _clamp(thrust, 0.0, max_thrust)
        if thrust > 0.0 and min_thrust > 0.0:
            thrust = max(min_thrust, thrust)

        status_tgo = "--" if tgo is None else f"{tgo:4.1f}s"
        self.status = (
            f"query_demo dx:{dx:6.1f} vy:{float(passive.vy_up):5.1f} "
            f"thr:{thrust:4.2f} tgo:{status_tgo}"
        )
        return BotAction(target_thrust=thrust, target_angle=angle_cmd, refuel=False)



def create_bot() -> QueryDemoBot:
    return QueryDemoBot()
