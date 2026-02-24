"""HUD overlay rendering for UI text."""

from __future__ import annotations

import math

from core.components import (
    CargoHold,
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    PhysicsState,
    SensorReadings,
    Transform,
    Wallet,
)
from core.maths import clearance_above_terrain


class HudOverlay:
    """Draw heads-up display text for lander status and controls."""

    def __init__(self, font, screen, bot=None):
        self.font = font
        self.screen = screen
        self.bot = bot

    def draw(self, level, bot=None, actor=None) -> None:
        focus_actor = actor if actor is not None else level.lander
        if not focus_actor:
            return
        screen_rect = self.screen.get_rect()

        # Caller can pass a bot override; fall back to the stored reference
        effective_bot = bot if bot is not None else self.bot

        info_lines = self._build_info_line_specs(level, focus_actor, effective_bot)
        self._draw_text_lines(info_lines, 10, (220, 220, 220))

        control_lines = self._build_control_lines(focus_actor)
        y_offset = screen_rect.bottom - 20 - (len(control_lines) * 18)
        self._draw_text_lines(control_lines, y_offset, (200, 200, 200))

    def _build_info_line_specs(self, level, actor, bot=None):
        lines = self._build_info_lines(level, actor, bot)
        specs: list[tuple[str, tuple[int, int, int] | None]] = []
        for line in lines:
            if line.startswith("THRUST:") and "[OD]" in line:
                specs.append((line, (255, 90, 90)))
            else:
                specs.append((line, None))
        return specs

    def _build_info_lines(self, level, actor, bot=None) -> list[str]:
        wallet = actor.get_component(Wallet)
        if wallet is None:
            raise RuntimeError("Lander missing Wallet component")
        trans = actor.get_component(Transform)
        phys = actor.get_component(PhysicsState)
        tank = actor.get_component(FuelTank)
        eng = actor.get_component(Engine)
        cargo = actor.get_component(CargoHold)
        geo = actor.get_component(LanderGeometry)
        ls = actor.get_component(LanderState)
        readings = actor.get_component(SensorReadings)
        if None in (trans, phys, tank, eng, geo, ls, readings):
            raise RuntimeError("Lander missing expected HUD components")

        def _stable(value: float, digits: int = 1) -> float:
            epsilon = 0.5 * (10.0 ** (-digits))
            return 0.0 if abs(value) < epsilon else value

        speed = math.hypot(phys.vel.x, phys.vel.y)
        terrain_y = level.terrain(trans.pos.x)
        altitude = clearance_above_terrain(
            trans.pos.y,
            terrain_y,
            body_height=geo.height,
        )
        prox = readings.proximity
        prox_dist = prox.distance if prox is not None else None
        prox_angle = prox.angle if prox is not None else None
        prox_angle_deg = math.degrees(prox_angle) if prox_angle is not None else None

        rotation_deg = math.degrees(trans.rotation)
        target_rot_deg = math.degrees(eng.target_angle)
        thrust_pct = eng.thrust_level * 100.0
        target_thrust_pct = eng.target_thrust * 100.0
        fuel_pct = 100.0 * tank.fuel / max(1e-6, tank.max_fuel)
        dry_mass = float(phys.mass)
        fuel_mass = float(tank.fuel) * float(tank.density)
        cargo_mass = 0.0
        cargo_limit = 0.0
        if cargo is not None:
            cargo_limit = max(0.0, float(cargo.max_cargo_mass))
            cargo_mass = max(0.0, min(float(cargo.cargo_mass), cargo_limit))
        wet_mass = dry_mass + fuel_mass + cargo_mass
        wet_mass_t = wet_mass / 1000.0
        dry_mass_t = dry_mass / 1000.0
        fuel_mass_t = fuel_mass / 1000.0
        cargo_mass_t = cargo_mass / 1000.0
        cargo_limit_t = cargo_limit / 1000.0
        weight_newton = max(1e-6, wet_mass * 9.8)
        normal_twr = max(0.0, float(eng.max_power)) / weight_newton
        boost_twr = max(0.0, float(eng.max_power) * float(eng.max_thrust)) / weight_newton
        ax = _stable(float(phys.acc.x), digits=2)
        ay = _stable(float(phys.acc.y), digits=2)
        acc_mag = _stable(math.hypot(ax, ay), digits=2)
        speed = _stable(speed, digits=1)
        altitude = _stable(altitude, digits=1)
        rotation_deg = _stable(rotation_deg, digits=1)
        target_rot_deg = _stable(target_rot_deg, digits=1)
        thrust_pct = _stable(thrust_pct, digits=0)
        target_thrust_pct = _stable(target_thrust_pct, digits=0)
        vx = _stable(float(phys.vel.x), digits=1)
        vy = _stable(float(phys.vel.y), digits=1)
        prox_dist_stable = (
            _stable(float(prox_dist), digits=1) if prox_dist is not None else None
        )
        prox_angle_deg_stable = (
            _stable(float(prox_angle_deg), digits=0) if prox_angle_deg is not None else None
        )

        lines: list[str] = [f"STATE: {ls.state.upper()}    CREDITS: {wallet.credits:.0f}"]
        if bot is not None:
            bot_name = getattr(bot, "_bot_name", None)
            if not isinstance(bot_name, str) or not bot_name:
                bot_name = bot.__class__.__module__.split(".")[-1]
            behavior = getattr(bot, "_bot_behavior", None)
            if not isinstance(behavior, str) or not behavior:
                prop_behavior = getattr(bot, "behavior", None)
                behavior = prop_behavior if isinstance(prop_behavior, str) else ""
            bot_label = f"{bot_name}:{behavior}" if behavior else bot_name
            lines.append(f"BOT: {bot_label}")
        lines.append("")
        lines.append(f"FUEL: {fuel_pct:.1f}% ({tank.fuel:.1f}/{tank.max_fuel:.1f})")
        if abs(target_thrust_pct - thrust_pct) < 1e-3:
            od_tag = " [OD]" if eng.thrust_level > 1.0 else ""
            lines.append(f"THRUST: {thrust_pct:.0f}%{od_tag}")
        else:
            od_tag = " [OD]" if (eng.thrust_level > 1.0 or eng.target_thrust > 1.0) else ""
            lines.append(f"THRUST: {thrust_pct:.0f}% -> {target_thrust_pct:.0f}%{od_tag}")
        if cargo is not None:
            lines.append(
                f"MASS: {wet_mass_t:.2f} t (dry {dry_mass_t:.2f}, fuel {fuel_mass_t:.2f}, "
                f"cargo {cargo_mass_t:.2f}/{cargo_limit_t:.2f} t)"
            )
        else:
            lines.append(
                f"MASS: {wet_mass_t:.2f} t (dry {dry_mass_t:.2f}, fuel {fuel_mass_t:.2f})"
            )

        lines.append("")
        lines.append(f"ALT: {altitude:.1f} m    SPEED: {speed:.1f} m/s")
        lines.append(f"V-SPEED: {vy:.1f} m/s    H-SPEED: {vx:.1f} m/s")
        lines.append(f"ACC: {acc_mag:.2f} m/s^2 (x {ax:.2f}, y {ay:.2f})")
        lines.append(f"TWR N/B: {normal_twr:.2f} / {boost_twr:.2f}")
        if abs(target_rot_deg - rotation_deg) < 0.5:
            lines.append(f"ANGLE: {rotation_deg:.1f}deg")
        else:
            lines.append(f"ANGLE: {rotation_deg:.1f}deg -> {target_rot_deg:.1f}deg")
        if prox_dist_stable is not None and prox_angle_deg_stable is not None:
            lines.append(f"PROX: {prox_dist_stable:.1f} m @ {prox_angle_deg_stable:.0f}deg")
        else:
            lines.append("PROX: --")
        return lines

    def _build_control_lines(self, lander) -> list[str]:
        _ = lander
        return [
            "Controls:",
            "W/UP: Increase thrust",
            "S/DOWN: Decrease thrust",
            "THRUST [OD] in red: overdrive burn",
            "A/LEFT: Rotate left",
            "D/RIGHT: Rotate right",
            "F: Refuel (when landed)",
            "TAB: Switch actor",
            "T: Toggle ballistic path",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def _draw_text_lines(self, lines, y_offset: int, color) -> None:
        for entry in lines:
            if isinstance(entry, tuple):
                line, line_color = entry
                draw_color = line_color if line_color is not None else color
            else:
                line = entry
                draw_color = color
            if line:
                shadow = self.font.render(line, True, (0, 0, 0))
                self.screen.blit(shadow, (11, y_offset + 1))
                text_surface = self.font.render(line, True, draw_color)
                self.screen.blit(text_surface, (10, y_offset))
            y_offset += 18
