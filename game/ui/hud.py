"""HUD overlay rendering for UI text."""

from __future__ import annotations

import math

from game.core.components import (
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
from game.core.maths import clearance_above_terrain


def _stable(value: float, digits: int = 1) -> float:
    """Round near-zero values to exactly zero for display stability."""
    epsilon = 0.5 * (10.0 ** (-digits))
    return 0.0 if abs(value) < epsilon else value


class HudOverlay:
    """Draw heads-up display text for lander status."""

    LINE_SPACING = 20

    def __init__(self, font, screen):
        self.font = font
        self.screen = screen

    def draw(self, level, bot=None, actor=None) -> None:
        focus_actor = actor if actor is not None else level.lander
        if not focus_actor:
            return
        specs = self._build_info_line_specs(level, focus_actor)
        self._draw_text_lines(specs, 10, (220, 220, 220))

    def _build_info_line_specs(self, level, actor):
        lines = self._build_info_lines(level, actor)
        specs: list[tuple[str, tuple[int, int, int] | None]] = []
        for line in lines:
            if "[OD]" in line:
                specs.append((line, (255, 90, 90)))
            else:
                specs.append((line, None))
        return specs

    def _build_info_lines(self, level, actor) -> list[str]:
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

        speed = math.hypot(phys.vel.x, phys.vel.y)
        terrain_y = level.terrain(trans.pos.x)
        altitude = clearance_above_terrain(
            trans.pos.y, terrain_y, body_height=geo.height
        )
        prox = readings.proximity
        prox_dist = prox.distance if prox is not None else None
        prox_angle_deg = (
            math.degrees(prox.angle) if prox is not None and prox.angle is not None else None
        )

        thrust_pct = _stable(eng.thrust_level * 100.0, digits=0)
        target_thrust_pct = _stable(eng.target_thrust * 100.0, digits=0)
        fuel_pct = _stable(100.0 * tank.fuel / max(1e-6, tank.max_fuel), digits=0)
        vx = _stable(float(phys.vel.x), digits=1)
        vy = _stable(float(phys.vel.y), digits=1)
        speed = _stable(speed, digits=1)
        altitude = _stable(altitude, digits=0)
        prox_dist_s = _stable(float(prox_dist), digits=0) if prox_dist is not None else None
        prox_angle_s = (
            _stable(float(prox_angle_deg), digits=0) if prox_angle_deg is not None else None
        )

        dry_mass = float(phys.mass)
        fuel_mass = float(tank.fuel) * float(tank.density)
        cargo_mass = cargo.effective_mass if cargo is not None else 0.0
        wet_mass_t = (dry_mass + fuel_mass + cargo_mass) / 1000.0

        # Line 1: credits / fuel / mass
        line1 = f"CR {wallet.credits:.0f}  FUEL {fuel_pct:.0f}%  MASS {wet_mass_t:.1f}t"

        # Line 2: thrust (with transition arrow and OD tag when relevant)
        od_tag = " [OD]" if (eng.thrust_level > 1.0 or eng.target_thrust > 1.0) else ""
        if abs(target_thrust_pct - thrust_pct) < 1e-3:
            line2 = f"THR {thrust_pct:.0f}%{od_tag}"
        else:
            line2 = f"THR {thrust_pct:.0f}% -> {target_thrust_pct:.0f}%{od_tag}"

        # Line 3: speeds
        line3 = f"SPD {speed:.1f} m/s  VX {vx:.1f} m/s  VY {vy:.1f} m/s"

        # Line 4: altitude + proximity
        if prox_dist_s is not None and prox_angle_s is not None:
            line4 = f"ALT {altitude:.0f} m  PROX {prox_dist_s:.0f} m @ {prox_angle_s:.0f} deg"
        else:
            line4 = f"ALT {altitude:.0f} m"

        return [line1, line2, line3, line4]

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
            y_offset += self.LINE_SPACING
