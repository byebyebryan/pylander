"""Sensor overlays for radar and proximity UI."""

from __future__ import annotations

import math
from core.maths import Range1D, Vector2


class SensorOverlay:
    """Render radar and proximity indicators."""

    def __init__(
        self,
        font,
        screen,
        landing_target_color,
        visited_landing_target_color,
        indicator_circle_size: float,
        height_scale: float,
    ):
        self.font = font
        self.screen = screen
        self.landing_target_color = landing_target_color
        self.visited_landing_target_color = visited_landing_target_color
        self.indicator_circle_size = indicator_circle_size
        self.height_scale = height_scale

    def draw(
        self,
        lander,
        terrain,
        targets,
        camera,
        contacts,
    ) -> None:
        if not lander:
            return
        self._draw_proximity(lander, terrain, targets, camera)
        self._draw_radar(contacts, camera)

    def _draw_proximity(self, lander, terrain, targets, camera) -> None:
        color = (128, 128, 128)
        proximity_radius_px = 50
        arrow_length_px = 14
        arrow_width_px = 12
        screen_rect = self.screen.get_rect()
        screen_center = Vector2(screen_rect.centerx, screen_rect.centery)

        proximity = lander.get_proximity_contact(terrain)
        if proximity is None:
            return

        proximity_screen = camera.world_to_screen(Vector2(proximity.x, proximity.y))
        sx, sy = proximity_screen.x, proximity_screen.y
        dx = sx - screen_center.x
        dy = sy - screen_center.y
        length_px = math.hypot(dx, dy)
        if length_px <= 0.0:
            return
        ux, uy = dx / length_px, dy / length_px
        span = Range1D.from_center(proximity.x, 0.0)
        if length_px > proximity_radius_px and (targets is None or not targets.get_targets(span)):
            bx, by = sx - ux * arrow_length_px, sy - uy * arrow_length_px
            px, py = -uy * arrow_width_px / 2.0, ux * arrow_width_px / 2.0
            lx, ly = bx + px, by + py
            rx, ry = bx - px, by - py
            self._line(color, (sx, sy), (int(lx), int(ly)))
            self._line(color, (sx, sy), (int(rx), int(ry)))

            tx, ty = sx - ux * arrow_length_px * 2, sy - uy * arrow_length_px * 2
            dist_str = f"{int(proximity.distance):d}m"
            d_surface = self.font.render(dist_str, True, color)
            self.screen.blit(
                d_surface,
                (tx - d_surface.get_width() // 2, ty - d_surface.get_height() // 2),
            )
        else:
            dist_str = f"{int(proximity.distance):d}m"
            d_surface = self.font.render(dist_str, True, color)
            tx = screen_rect.centerx - d_surface.get_width() // 2
            ty = screen_rect.centery - d_surface.get_height() // 2 - 20
            self.screen.blit(d_surface, (tx, ty))

    def _draw_radar(self, contacts, camera) -> None:
        if not contacts:
            return
        screen_rect = self.screen.get_rect()
        circle_radius_px = int(
            screen_rect.height * self.indicator_circle_size * 0.5
        )

        cx = screen_rect.centerx
        cy = screen_rect.centery

        for c in contacts:
            color = (
                self.visited_landing_target_color
                if (getattr(c, "info", None) and c.info.get("award", 1) == 0)
                else self.landing_target_color
            )

            inside_drawn = False
            if c.x is not None and c.y is not None:
                tx, ty = c.x, c.y * self.height_scale
                screen_pt = camera.world_to_screen(Vector2(tx, ty))
                sx, sy = screen_pt.x, screen_pt.y
                dx = sx - cx
                dy = sy - cy
                dist_px = math.hypot(dx, dy)
                if dist_px <= circle_radius_px:
                    if c.distance is not None:
                        dist_str = f"{int(c.distance):d}m"
                        d_surface = self.font.render(dist_str, True, color)
                        self.screen.blit(
                            d_surface, (sx - d_surface.get_width() // 2, sy + 6)
                        )
                    inside_drawn = True

            if inside_drawn:
                continue

            ux = math.cos(c.angle)
            uy_screen = -math.sin(c.angle)
            ex = int(cx + ux * circle_radius_px)
            ey = int(cy + uy_screen * circle_radius_px)

            arrow_len = 14.0
            arrow_w = 12.0

            bx = ex - ux * arrow_len
            by = ey - uy_screen * arrow_len

            pxv = -uy_screen
            pyv = ux

            lx = bx + pxv * (arrow_w / 2.0)
            ly = by + pyv * (arrow_w / 2.0)
            rx = bx - pxv * (arrow_w / 2.0)
            ry = by - pyv * (arrow_w / 2.0)

            self._line(color, (ex, ey), (int(lx), int(ly)))
            self._line(color, (ex, ey), (int(rx), int(ry)))

            if c.distance is not None:
                tx2, ty2 = ex - ux * arrow_len * 2, ey - uy_screen * arrow_len * 2
                dist_str = f"{int(c.distance):d}m"
                d_surface = self.font.render(dist_str, True, color)
                self.screen.blit(
                    d_surface,
                    (
                        tx2 - d_surface.get_width() // 2,
                        ty2 - d_surface.get_height() // 2,
                    ),
                )

    def _line(self, color, p1, p2) -> None:
        import pygame

        pygame.draw.line(self.screen, color, p1, p2, 2)
