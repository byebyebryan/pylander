"""Rendering system for terrain visualization (Level-centric)."""

import os
import random
import pygame
from .camera import OffsetCamera, Camera
from .minimap import Minimap
from typing import TYPE_CHECKING
import math
from .auto_zoom import AutoZoomController
from .hud import HudOverlay
from .overlays import SensorOverlay
from .fps_overlay import FpsOverlay
from core.maths import Range1D
from core.components import (
    Engine,
    FuelTank,
    LanderGeometry,
    LanderState,
    SensorReadings,
    Transform,
)
from core.ecs import require_component
from core.lander_visuals import Thrust
from core.maths import RigidTransform2, Vector2

if TYPE_CHECKING:
    from core.level import Level
    from core.bot import Bot


class Renderer:
    """Handles all rendering operations for the terrain app."""

    def _get_body_polygon(self, entity) -> list[Vector2]:
        trans = require_component(entity, Transform)
        geo = require_component(entity, LanderGeometry)
        local = geo.polygon_points
        if not local:
            half_w = geo.width / 2.0
            half_h = geo.height / 2.0
            local = [
                Vector2(0.0, half_h),
                Vector2(-half_w, -half_h),
                Vector2(half_w, -half_h),
            ]
        tf = RigidTransform2(trans.pos, trans.rotation)
        return [tf.apply(pt) for pt in local]

    def _get_actor_entities(self) -> list:
        actors = getattr(self.level.world, "actors", None)
        if actors:
            return list(actors)
        return [self.level.lander] if self.level.lander is not None else []

    def _get_thrusts(self, entity) -> list[Thrust]:
        trans = entity.get_component(Transform)
        geo = entity.get_component(LanderGeometry)
        eng = entity.get_component(Engine)
        tank = entity.get_component(FuelTank)
        if None in (trans, geo, eng, tank):
            return []
        if eng.thrust_level <= 0.0 or tank.fuel <= 0.0:
            return []
        half_h = geo.height / 2.0
        local_base = Vector2(0.0, -half_h * 1.5)
        tf = RigidTransform2(trans.pos, trans.rotation)
        world_base = tf.apply(local_base)
        cos_r = math.cos(trans.rotation)
        sin_r = math.sin(trans.rotation)
        world_angle = math.atan2(-cos_r, -sin_r)
        return [
            Thrust(
                x=world_base.x,
                y=world_base.y,
                angle=world_angle,
                width=geo.width / 2.0,
                length=20.0,
                power=eng.thrust_level,
            )
        ]

    def __init__(self, level: "Level", width: int, height: int, bot: "Bot | None" = None):
        """Initialize renderer with level reference and manage display/clock."""
        self.level = level
        self.bot = bot
        self.design_width = int(width)
        self.design_height = int(height)
        # Avoid forcing an OpenGL context; some environments set this and lack GLX.
        os.environ.pop("PYGAME_FORCE_OPENGL", None)
        # Prefer EGL or software paths over GLX when available to avoid X_GLXCreateContext failures.
        os.environ.setdefault("SDL_VIDEO_X11_FORCE_EGL", "1")
        os.environ.setdefault("SDL_RENDER_DRIVER", "software")
        pygame.init()
        self.window_surface = pygame.display.set_mode((width, height))
        title = "Lunar Lander"
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        # Render to a fixed logical canvas, then scale to the real window.
        # This keeps camera/UI layout stable even when the OS force-resizes.
        self.screen = pygame.Surface((self.design_width, self.design_height)).convert()
        self._scaled_surface: pygame.Surface | None = None
        # Renderer owns the main camera
        self.main_camera = Camera(self.design_width, self.design_height)
        # Auto-zoom controller is owned by the renderer
        self.auto_zoom = AutoZoomController(delay_seconds=3.0, response_rate=1.0)

        # Colors
        self.bg_color = (20, 20, 25)
        self.terrain_color = (255, 255, 255)
        self.reference_circle_color = (255, 100, 100)
        self.landing_target_color = (50, 255, 50)
        self.visited_landing_target_color = (255, 255, 0)
        self.lander_color = (255, 200, 50)
        self.thrust_color = (255, 100, 0)

        self.thrust_flame_length = 20
        self.thrust_flame_color_low = (255, 0, 0)
        self.thrust_flame_color_high = (255, 255, 0)
        self.thrust_flame_color_overdrive = (255, 80, 80)

        # Terrain rendering settings
        self.height_scale = 1.0  # Vertical scale for terrain height (in world units)
        self.target_segments = 80  # Target number of segments across screen

        # Create minimap
        self.minimap = Minimap(
            self.design_width,
            self.design_height,
            self.level.terrain,
        )

        # UI fonts
        self.font = pygame.font.SysFont("monospace", 14)
        self.large_font = pygame.font.SysFont("monospace", 32, bold=True)
        self.hud = HudOverlay(self.font, self.screen, bot=self.bot)

        self.indicator_circle_size = 0.8

        # Orientation inset (center) shown when zoomed far out
        self.orientation_inset_trigger_zoom = 1.0  # show inset when zoom <= this
        self.orientation_inset_scale_px_per_world = 2.0  # fixed zoom for inset
        self.sensor_overlay = SensorOverlay(
            self.font,
            self.screen,
            self.landing_target_color,
            self.visited_landing_target_color,
            self.indicator_circle_size,
            self.height_scale,
        )
        self.fps_overlay = FpsOverlay(self.font, self.screen, self.clock)

    def tick(self, target_fps: int) -> float:
        """Tick internal clock and return frame dt in seconds."""
        return self.clock.tick(target_fps) / 1000.0

    def update(self, dt: float):
        """Update camera follow and auto-zoom based on level state."""
        lander = self.level.lander
        if lander:
            trans = require_component(lander, Transform)
            state = require_component(lander, LanderState)
            if state.state == "flying":
                self.main_camera.x = trans.pos.x
                self.main_camera.y = trans.pos.y

        def _height_at(xx: float) -> float:
            return self.level.terrain(xx)

        self.auto_zoom.update(
            dt, _height_at, self.main_camera, self.get_screen_height()
        )

    def get_screen_height(self) -> int:
        return self.screen.get_height()

    def shutdown(self):
        try:
            pygame.quit()
        except Exception:
            pass

    def _terrain_resolution(self, lod: int) -> float:
        get_resolution = getattr(self.level.terrain, "get_resolution", None)
        if callable(get_resolution):
            try:
                return max(1e-6, float(get_resolution(lod)))
            except Exception:
                return 2.0
        return 2.0

    def _pick_lod_for_world_step(self, world_step: float, max_lod: int = 8) -> int:
        target = max(1e-6, float(world_step))
        best_lod = 0
        best_score = float("inf")
        for lod in range(max(0, int(max_lod)) + 1):
            res = self._terrain_resolution(lod)
            score = abs(math.log2(res / target))
            if score < best_score:
                best_lod = lod
                best_score = score
        return best_lod

    def draw_terrain(self):
        """Draw terrain as a polyline sampled on a stable world grid to reduce shimmer."""
        visible = self.main_camera.get_visible_world_rect()
        world_span = visible.width

        # Choose a world-step based on target segments and anchor it to a world grid
        if self.target_segments <= 0:
            self.target_segments = 80
        desired_step = world_span / max(1, self.target_segments)
        lod = self._pick_lod_for_world_step(desired_step)
        base_interval = self._terrain_resolution(lod)
        world_step = max(desired_step, base_interval)

        profile_fn = getattr(self.level.terrain, "profile", None)
        if callable(profile_fn):
            samples = profile_fn(
                visible.min_x,
                visible.max_x + world_step,
                lod=lod,
                step=world_step,
            )
        else:
            start_world_x = math.floor(visible.min_x / world_step) * world_step
            end_world_x = visible.max_x + world_step
            samples = []
            wx = start_world_x
            while wx <= end_world_x:
                samples.append((wx, self.level.terrain(wx, lod=lod)))
                wx += world_step

        screen_points = [
            self.main_camera.world_to_screen(Vector2(wx, wy * self.height_scale))
            for wx, wy in samples
        ]

        if len(screen_points) >= 2:
            # Anti-aliased lines to reduce visual shimmer
            pygame.draw.aalines(self.screen, self.terrain_color, False, screen_points)

    def _get_radar_contacts(self):
        lander = self.level.lander
        if lander is None:
            return []
        readings = require_component(lander, SensorReadings)
        return readings.radar_contacts

    def draw_targets(self, contacts=None):
        # Prefer canonical site projections for world-accurate visuals.
        sites = getattr(self.level, "sites", None)
        if sites is not None and hasattr(sites, "get_sites"):
            visible = self.main_camera.get_visible_world_rect()
            center_x = (visible.min_x + visible.max_x) * 0.5
            span = Range1D.from_center(center_x, visible.width * 0.5)
            for s in sites.get_sites(span):
                tx = s.x
                ty = s.y * self.height_scale
                half = s.size * 0.5
                start_pos = self.main_camera.world_to_screen(Vector2(tx - half, ty))
                end_pos = self.main_camera.world_to_screen(Vector2(tx + half, ty))
                color = (
                    self.visited_landing_target_color
                    if (getattr(s, "visited", False) or getattr(s, "award", 1.0) == 0.0)
                    else self.landing_target_color
                )
                pygame.draw.line(self.screen, color, start_pos, end_pos, 4)

                # Elevated/decoupled pads need explicit support visuals.
                if (not getattr(s, "terrain_bound", True)) or getattr(
                    s, "terrain_mode", ""
                ) == "elevated_supports":
                    support_xs = (tx - half * 0.7, tx + half * 0.7)
                    for sx in support_xs:
                        ground_y = self.level.terrain(sx) * self.height_scale
                        top = self.main_camera.world_to_screen(Vector2(sx, ty))
                        base = self.main_camera.world_to_screen(Vector2(sx, ground_y))
                        pygame.draw.line(self.screen, color, top, base, 2)
            return

        # Fallback to radar contacts when site model is unavailable.
        if contacts is None:
            contacts = self._get_radar_contacts()
        for c in contacts:
            if c.x is None or c.y is None or c.size is None:
                continue
            tx = c.x
            ty = c.y * self.height_scale
            half = c.size / 2.0
            start_pos = self.main_camera.world_to_screen(Vector2(tx - half, ty))
            end_pos = self.main_camera.world_to_screen(Vector2(tx + half, ty))
            color = (
                self.visited_landing_target_color
                if (getattr(c, "info", None) and c.info.get("award", 1) == 0)
                else self.landing_target_color
            )
            pygame.draw.line(self.screen, color, start_pos, end_pos, 4)

    def draw_actor(self, entity, camera):
        """Draw one actor if it has lander geometry and transform."""
        if entity is None:
            return
        if entity.get_component(LanderGeometry) is None or entity.get_component(Transform) is None:
            return
        poly_world = self._get_body_polygon(entity)
        rotated_points = []
        for world_pt in poly_world:
            rotated_points.append(camera.world_to_screen(world_pt))
            
        if rotated_points:
            pygame.draw.polygon(self.screen, (255, 255, 255), rotated_points, 2)

    def draw_thrusts(self, thrusts, camera):
        """Draw inverted V shaped thrust flames given thrust descriptors.

        Each thrust provides base center (x,y), direction angle, base width, and
        length. We draw two lines from the tip back to the base corners.
        """
        if not thrusts:
            return

        for t in thrusts:
            # Compute tip point in world using angle (0 along +x, CCW, y-up)
            ux = math.cos(t.angle)
            uy = math.sin(t.angle)

            width = t.width / 2.0 + t.power * (t.width / 2.0)
            width *= 0.9 + 0.2 * random.random()

            length = t.length * t.power
            length *= 0.9 + 0.2 * random.random()

            tip_x = t.x + ux * length
            tip_y = t.y + uy * length

            # Base corners: perpendicular to direction at base center
            px = -uy
            py = ux
            half_w = width / 2.0
            left_x = t.x + px * half_w
            left_y = t.y + py * half_w
            right_x = t.x - px * half_w
            right_y = t.y - py * half_w

            # Color gradient based on power; overdrive has explicit warning color.
            if t.power > 1.0:
                color = self.thrust_flame_color_overdrive
            else:
                p = max(0.0, min(1.0, t.power))
                low = self.thrust_flame_color_low
                high = self.thrust_flame_color_high
                color = (
                    int(low[0] * (1 - p) + high[0] * p),
                    int(low[1] * (1 - p) + high[1] * p),
                    int(low[2] * (1 - p) + high[2] * p),
                )

            # Transform to screen space and draw two lines
            tip_pos = camera.world_to_screen(Vector2(tip_x, tip_y))
            left_pos = camera.world_to_screen(Vector2(left_x, left_y))
            right_pos = camera.world_to_screen(Vector2(right_x, right_y))
            
            pygame.draw.aaline(self.screen, color, tip_pos, left_pos)
            pygame.draw.aaline(self.screen, color, tip_pos, right_pos)

    def draw_ui(self):
        """Draw UI text: credits and focused-actor flight stats."""
        self.hud.draw(self.level, self.bot)

    def draw(self):
        """Render the complete scene."""
        # Clear background
        self.screen.fill(self.bg_color)

        # Draw terrain
        self.draw_terrain()

        # Draw landing targets
        contacts = self._get_radar_contacts()
        self.draw_targets(contacts)

        # Draw sensor overlays
        proximity = None
        if self.level.lander is not None:
            proximity = require_component(self.level.lander, SensorReadings).proximity
        self.sensor_overlay.draw(
            proximity,
            self.level.sites,
            self.main_camera,
            contacts,
        )

        # Draw actors and thrust flames
        for actor in self._get_actor_entities():
            self.draw_actor(actor, self.main_camera)
            self.draw_thrusts(self._get_thrusts(actor), self.main_camera)

        # Draw minimap
        self.minimap.draw(
            self.screen,
            self.main_camera,
            self.height_scale,
            contacts=contacts,
            sites=self.level.sites,
        )

        # Draw center orientation inset when zoomed far out
        if (
            self.level.lander
            and self.main_camera.zoom <= self.orientation_inset_trigger_zoom
        ):
            self.draw_lander_orientation_inset()

        # Draw UI overlay
        self.draw_ui()

        # Always draw FPS overlay (top-right)
        self.fps_overlay.draw()
        self._present_to_window()
        pygame.display.flip()

    def _present_to_window(self) -> None:
        window = pygame.display.get_surface() or self.window_surface
        if window is None:
            return

        window_w, window_h = window.get_size()
        if window_w <= 0 or window_h <= 0:
            return

        scale = min(window_w / self.design_width, window_h / self.design_height)
        target_w = max(1, int(round(self.design_width * scale)))
        target_h = max(1, int(round(self.design_height * scale)))
        target_x = (window_w - target_w) // 2
        target_y = (window_h - target_h) // 2

        window.fill(self.bg_color)
        if target_w == self.design_width and target_h == self.design_height:
            window.blit(self.screen, (target_x, target_y))
            return

        if (
            self._scaled_surface is None
            or self._scaled_surface.get_width() != target_w
            or self._scaled_surface.get_height() != target_h
        ):
            self._scaled_surface = pygame.Surface((target_w, target_h)).convert()

        pygame.transform.smoothscale(
            self.screen,
            (target_w, target_h),
            self._scaled_surface,
        )
        window.blit(self._scaled_surface, (target_x, target_y))

    # draw_proximity_ui/draw_radar_ui moved to SensorOverlay

    # draw_fps moved to FpsOverlay

    def draw_lander_orientation_inset(self):
        """Draw a fixed-zoom lander view in a rectangle at the bottom-right.

        The rectangle matches the minimap size and is placed at the bottom-right
        of the main screen.
        """
        lander = self.level.lander
        if not lander:
            return
        trans = require_component(lander, Transform)

        # Rectangle same size as minimap, positioned at bottom-right of screen
        mm = self.minimap
        margin = getattr(mm, "margin", 10)
        rect = pygame.Rect(
            int(self.screen.get_width() - mm.rect.width - margin),
            int(self.screen.get_height() - mm.rect.height - margin),
            int(mm.rect.width),
            int(mm.rect.height),
        )

        # Background and border similar to minimap styling
        bg_color = getattr(mm, "bg_color", (0, 0, 0))
        border_color = getattr(mm, "border_color", (200, 200, 200))
        pygame.draw.rect(self.screen, bg_color, rect)
        pygame.draw.rect(self.screen, border_color, rect, 2)

        cx, cy = rect.center

        # Use an OffsetCamera centered on the lander with fixed inset scale
        scale = self.orientation_inset_scale_px_per_world
        inset_cam = OffsetCamera(trans.pos.x, trans.pos.y, scale, cx, cy)

        # Clip drawing to the interior of the rectangle (minus border)
        prev_clip = self.screen.get_clip()
        try:
            self.screen.set_clip(rect.inflate(-2, -2))
            # Reuse standard draw paths with the inset camera
            self.draw_actor(lander, inset_cam)
            self.draw_thrusts(self._get_thrusts(lander), inset_cam)
        finally:
            self.screen.set_clip(prev_clip)
