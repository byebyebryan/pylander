"""Turtle bot implementation (cautious controller)."""

from __future__ import annotations

import math

from bot import Bot, PassiveSensors, ActiveSensors, BotAction


class TurtleBot(Bot):
    """Turtle bot - cautious controller that prioritizes safety over speed."""

    def __init__(self):
        super().__init__()
        self._prev_angle_cmd = 0.0
        self._brake_latch = False
        self._prev_dx_sign = 0

    def update(
        self, dt: float, passive: PassiveSensors, active: ActiveSensors
    ) -> BotAction:
        state = passive.state

        # Handle terminal states via game; just emit neutral action
        if state in ("landed", "crashed", "out_of_fuel"):
            action = BotAction(0.0, passive.angle, False)
            action.status = state.upper()
            self.status = action.status
            return action

        # Target selection via radar (nearest contact first)
        contacts = passive.radar_contacts or []
        angle_to_target = 0.0
        est_distance = None
        target_world_y = None
        if contacts:
            # Prefer a lower target (downhill) to avoid climbing; fallback to first
            chosen = None
            for c in contacts:
                if c.y is None:
                    break
                cy = c.y
                # y-up: pick targets below current altitude (smaller y)
                if cy <= passive.altitude - 2.0:
                    chosen = c
                    break
            if chosen is None:
                chosen = contacts[0]
            angle_to_target = chosen.angle
            est_distance = chosen.distance
            target_world_y = chosen.y

        # Passive proximity (ground clearance as radar altimeter)
        prox = passive.proximity
        alt_ground = prox.distance if prox is not None else None
        # Adjust for lander height: contact occurs when clearance ~= height/2
        half_height = 0.5 * (
            self.vehicle_info.get("height", 8.0)
            if isinstance(getattr(self, "vehicle_info", None), dict)
            else 8.0
        )
        alt = (alt_ground - half_height) if alt_ground is not None else 1e9

        # Velocity-direction active raycast for hazard prediction (ballistic proxy)
        vx = passive.vx
        vy_up = passive.vy_up
        speed = math.hypot(vx, vy_up)
        hazard = False
        hazard_dist = float("inf")
        if callable(getattr(active, "raycast", None)) and (abs(vx) + abs(vy_up) > 1e-3):
            # y-up world: cast along velocity with slight downward bias (negative y)
            dy_world = vy_up
            dir_angle = math.atan2(dy_world - 0.35 * speed, vx)
            horizon = 3.0  # seconds lookahead
            max_rng = max(50.0, min(2000.0, speed * horizon))
            rc = active.raycast(dir_angle, max_rng)
            if rc and rc.get("hit", False):
                hazard_dist = float(rc.get("distance", 0.0))
                hazard = hazard_dist < max(20.0, speed * 2.0)

        # Phasing by estimated distance
        far = est_distance is None or est_distance > 1500.0
        mid = est_distance is not None and 200.0 < est_distance <= 1500.0
        near = est_distance is not None and est_distance <= 200.0

        # Aggressive horizontal speed target toward target direction with stopping-distance cap
        dir_sign = 1.0 if math.cos(angle_to_target) >= 0.0 else -1.0
        top_speed = 25.0
        hazard_cap = 18.0 if hazard else top_speed
        allowed = hazard_cap
        # If we have distance, cap speed by stopping distance s = v^2/2a => v <= sqrt(2 a s)
        if est_distance is not None:
            m_cap = max(0.5, passive.mass if hasattr(passive, "mass") else 2.0)
            max_thrust_power = (
                self.vehicle_info.get("max_thrust_power", 50.0)
                if isinstance(getattr(self, "vehicle_info", None), dict)
                else 50.0
            )
            a_lat_cap = (max_thrust_power / m_cap) * math.sin(0.65)
            a_lat_cap = max(1e-3, a_lat_cap)
            v_cap = math.sqrt(
                max(0.0, 2.0 * a_lat_cap * max(0.0, abs(est_distance) - 10.0))
            )
            allowed = min(allowed, max(14.0, v_cap))
        # Range-based fallback caps
        if near:
            allowed = min(allowed, 40.0)
        elif mid:
            allowed = min(allowed, 45.0)
        vx_sp = dir_sign * allowed
        # Horizontal distance to target if known
        dx_to_target = None
        if est_distance is not None:
            dx_to_target = math.cos(angle_to_target) * est_distance
        # Track sign for overshoot detection
        dx_sign = 0
        if dx_to_target is not None and abs(dx_to_target) > 1e-6:
            dx_sign = 1 if dx_to_target > 0 else -1

        # Determine if target is above/below (y-up)
        target_below = False
        if target_world_y is not None:
            target_below = target_world_y <= passive.altitude - 2.0

        # Vertical velocity target (up +). Negative values descend.
        # If no proximity, descend faster based on estimated dy to target.
        if alt_ground is None and est_distance is not None:
            dy_to_target = math.sin(angle_to_target) * est_distance
            if dy_to_target > 0:
                vy_sp = -min(7.0, 0.08 * dy_to_target + 2.5)
            else:
                vy_sp = -4.5
        else:
            if alt < 6.0:
                vy_sp = -0.45
            elif alt < 12.0:
                vy_sp = -1.10
            elif alt < 30.0:
                vy_sp = -2.20
            elif alt < 60.0:
                vy_sp = -3.40
            elif alt < 80.0:
                vy_sp = -4.60
            else:
                vy_sp = -5.20

        # Clearance requirements scale with speed; include half-height margin (stronger)
        min_clearance = half_height + 12.0 + 0.50 * speed
        need_climb_for_clearance = (alt_ground is not None) and (
            alt_ground < min_clearance
        )

        # No strategic climbing: only emergency small lift if critically low clearance
        if alt_ground is not None and alt_ground < (half_height + 2.0):
            vy_sp = max(vy_sp, 1.2)

        # Do not dive below the target while far in x; hold altitude band above pad
        if (dx_to_target is not None) and (abs(dx_to_target) > 80.0) and target_below:
            band_above = half_height + 12.0
            if alt_ground is not None and alt_ground < band_above:
                vy_sp = max(vy_sp, 1.6)

        # Predictive braking: when within stopping distance, brake (latched)
        braking = False
        m_for_brake = max(0.5, passive.mass if hasattr(passive, "mass") else 2.0)
        max_thrust_power = (
            self.vehicle_info.get("max_thrust_power", 50.0)
            if isinstance(getattr(self, "vehicle_info", None), dict)
            else 50.0
        )
        vx_deadband = 0.8
        if dx_to_target is not None:
            a_lat_cap = (max_thrust_power / m_for_brake) * math.sin(0.65)
            a_lat_cap = max(1e-3, a_lat_cap)
            s_stop = (vx * vx) / (2.0 * a_lat_cap)
            # Release latch if we crossed to the other side of target
            if self._brake_latch and (
                self._prev_dx_sign != 0
                and dx_sign != 0
                and dx_sign != self._prev_dx_sign
            ):
                self._brake_latch = False
            if self._brake_latch:
                braking = True
                if (abs(vx) <= vx_deadband) and (abs(dx_to_target) <= 5.0):
                    self._brake_latch = False
                    braking = False
            else:
                if abs(dx_to_target) <= (s_stop * 1.15 + 6.0):
                    self._brake_latch = True
                    braking = True

        # Position-based horizontal speed command for better alignment and recovery
        if dx_to_target is not None:
            t_align = 2.0 if far else 1.0 if mid else 0.6
            vx_pos = max(-allowed, min(allowed, dx_to_target / max(t_align, 1e-3)))
            if braking:
                vx_sp = vx_pos
            else:
                vx_sp = 0.3 * vx_sp + 0.7 * vx_pos

        # Desired lateral acceleration (PD on vx with damping by measured ax)
        a_x_meas = getattr(passive, "ax", 0.0)
        k_vx_p = 0.9 if braking else 0.5
        k_vx_d = 0.40 if braking else 0.15
        vx_err = vx_sp - vx
        if braking and abs(vx_err) < vx_deadband:
            vx_err = 0.0
        a_x_sp = k_vx_p * vx_err - k_vx_d * a_x_meas

        # Map desired lateral accel to tilt using asin((a_x * m)/T)
        angle = passive.angle
        mass = max(0.5, passive.mass if hasattr(passive, "mass") else 2.0)
        hover_thrust = (9.8 * mass) / max(0.2, abs(math.cos(angle)))
        thrust_budget = max(0.0, max_thrust_power - hover_thrust)
        effective_thrust = max(
            1e-3, min(max_thrust_power, hover_thrust + thrust_budget)
        )
        req = (a_x_sp * mass) / effective_thrust
        req = max(-0.99, min(0.99, req))
        # With CW-from-up angles and thrust along (sin r, cos r), +angle tilts right.
        # To produce +a_x (rightward), use positive angle.
        angle_cmd = math.asin(req)

        # Tilt limits; tighter when low/hazard/braking
        max_tilt = 1.00
        if (alt < 20.0) or hazard or need_climb_for_clearance or braking:
            max_tilt = 0.55
        angle_cmd = max(-max_tilt, min(max_tilt, angle_cmd))
        # Slew limit angle command to reduce oscillations (slower near ground)
        max_rate = 1.6 if alt < 30.0 else 2.2  # rad/s
        max_delta = max_rate * max(dt, 1e-3)
        angle_cmd = max(
            self._prev_angle_cmd - max_delta,
            min(self._prev_angle_cmd + max_delta, angle_cmd),
        )
        self._prev_angle_cmd = angle_cmd

        # Decisive touchdown window using known safe tolerances
        safe_v = (
            self.vehicle_info.get("safe_landing_velocity", 10.0)
            if isinstance(getattr(self, "vehicle_info", None), dict)
            else 10.0
        )
        landing_window = False
        if (dx_to_target is not None) and (
            abs(dx_to_target)
            <= max(
                3.0,
                (
                    self.vehicle_info.get("width", 5.0)
                    if isinstance(getattr(self, "vehicle_info", None), dict)
                    else 5.0
                )
                * 0.6,
            )
        ):
            if alt <= 2.5:
                landing_window = True
        landing_mode = False
        if landing_window:
            landing_mode = True
            angle_cmd = 0.0
            # zero lateral accel so we don't tilt during flare
            a_x_sp = 0.0
            # commit to descend within tolerances (avoid hover)
            vy_sp = -min(1.5, safe_v * 0.8)

        # Mass-aware hover baseline with tilt loss
        angle = passive.angle
        mass = max(0.5, passive.mass if hasattr(passive, "mass") else 2.0)
        hover = (9.8 / 25.0) * (mass / 2.0) / max(0.2, abs(math.cos(angle)))

        # Vertical control
        k_alt_p = 0.020
        k_vy_p = 0.135
        e_alt = 0.0
        if landing_mode:
            e_alt = 0.0
        elif alt_ground is not None:
            alt_sp = 34.0 if far else 18.0 if mid else 3.2
            e_alt = alt_sp - alt
        e_vy = vy_sp - vy_up
        target_thrust = hover + (k_alt_p * e_alt) + (k_vy_p * e_vy)

        # Extra braking near terrain when descending fast
        if (alt_ground is not None) and (alt < 18.0) and (vy_up < -2.0):
            target_thrust += 0.12

        # Clamp
        target_thrust = max(0.0, min(1.0, target_thrust))

        status = (
            f"prox:{(alt_ground if alt_ground is not None else float('inf')):.0f} "
            f"vx:{vx:.1f} vy:{vy_up:.1f}"
            + (" HZD" if hazard else "")
            + (" BRK" if braking else "")
        )

        action = BotAction(
            target_thrust,
            angle_cmd,
            False,
            status=status,
        )
        self.status = action.status
        # Persist latest dx sign for next cycle
        self._prev_dx_sign = dx_sign
        return action


def create_bot() -> Bot:
    return TurtleBot()


__all__ = ["TurtleBot", "create_bot"]
