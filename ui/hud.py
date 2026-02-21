"""HUD overlay rendering for UI text."""

from __future__ import annotations

import math

from core.components import Engine, FuelTank, LanderState, PhysicsState, SensorReadings, Transform, Wallet


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

        info_lines = self._build_info_lines(level, focus_actor, effective_bot)
        self._draw_text_lines(info_lines, 10, (220, 220, 220))

        control_lines = self._build_control_lines(focus_actor)
        y_offset = screen_rect.bottom - 20 - (len(control_lines) * 18)
        self._draw_text_lines(control_lines, y_offset, (200, 200, 200))

    def _build_info_lines(self, level, actor, bot=None) -> list[str]:
        wallet = actor.get_component(Wallet)
        if wallet is None:
            raise RuntimeError("Lander missing Wallet component")
        trans = actor.get_component(Transform)
        phys = actor.get_component(PhysicsState)
        tank = actor.get_component(FuelTank)
        eng = actor.get_component(Engine)
        ls = actor.get_component(LanderState)
        readings = actor.get_component(SensorReadings)
        if None in (trans, phys, tank, eng, ls, readings):
            raise RuntimeError("Lander missing expected HUD components")

        speed = math.hypot(phys.vel.x, phys.vel.y)
        altitude = trans.pos.y - level.terrain(trans.pos.x)
        prox = readings.proximity
        prox_dist = prox.distance if prox is not None else None
        prox_angle = prox.angle if prox is not None else None
        prox_angle_deg = math.degrees(prox_angle) if prox_angle is not None else None

        rotation_deg = math.degrees(trans.rotation)
        target_rot_deg = math.degrees(eng.target_angle)
        thrust_pct = eng.thrust_level * 100.0
        target_thrust_pct = eng.target_thrust * 100.0

        lines: list[str] = [f"CREDITS: {wallet.credits:.0f}"]
        lines.append("")
        lines.append(f"FUEL: {tank.fuel:.1f}%")
        if abs(target_thrust_pct - thrust_pct) < 1e-3:
            lines.append(f"THRUST: {thrust_pct:.0f}%")
        else:
            lines.append(f"THRUST: {thrust_pct:.0f}% -> {target_thrust_pct:.0f}%")
        if abs(target_rot_deg - rotation_deg) < 0.5:
            lines.append(f"ANGLE: {rotation_deg:.1f}deg")
        else:
            lines.append(f"ANGLE: {rotation_deg:.1f}deg -> {target_rot_deg:.1f}deg")

        lines.append("")
        lines.append(f"SPEED: {speed:.1f} m/s")
        lines.append(f"ALT: {altitude:.1f} m")
        lines.append(f"H-SPEED: {phys.vel.x:.1f} m/s")
        lines.append(f"V-SPEED: {phys.vel.y:.1f} m/s")
        if prox_dist is not None and prox_angle_deg is not None:
            lines.append(f"PROX: {prox_dist:.1f} m @ {prox_angle_deg:.0f}deg")
        else:
            lines.append("PROX: --")

        lines.append("")
        lines.append(f"STATE: {ls.state.upper()}")
        if bot is not None and hasattr(bot, "get_stats_text"):
            lines.extend(bot.get_stats_text())
        return lines

    def _build_control_lines(self, lander) -> list[str]:
        _ = lander
        return [
            "Controls:",
            "W/UP: Increase thrust",
            "S/DOWN: Decrease thrust",
            "A/LEFT: Rotate left",
            "D/RIGHT: Rotate right",
            "F: Refuel (when landed)",
            "TAB: Switch actor",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def _draw_text_lines(self, lines: list[str], y_offset: int, color) -> None:
        for line in lines:
            if line:
                shadow = self.font.render(line, True, (0, 0, 0))
                self.screen.blit(shadow, (11, y_offset + 1))
                text_surface = self.font.render(line, True, color)
                self.screen.blit(text_surface, (10, y_offset))
            y_offset += 18
