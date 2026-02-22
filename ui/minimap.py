"""Minimap display showing camera position and terrain overview."""

import pygame
from core.maths import Range1D, Rect, Size2, Vector2
from .camera import Camera, OffsetCamera


class Minimap:
    """Minimap showing terrain overview and current viewport."""

    def __init__(self, screen_width: int, screen_height: int, terrain):
        """Initialize minimap.

        Args:
            screen_width: Width of main screen
            screen_height: Height of main screen
            terrain: Terrain generator for getting terrain data
        """
        self.terrain = terrain
        # Minimap size (proportional to screen)
        minimap_scale = 0.25
        self.size = Size2(
            w=int(screen_width * minimap_scale),
            h=int(screen_height * minimap_scale),
        )
        self.margin = 10

        # Position (top-right corner)
        self.rect = Rect(
            x=screen_width - self.size.w - self.margin,
            y=self.margin,
            w=self.size.w,
            h=self.size.h,
        )

        # Minimap has its own camera for coordinate transforms
        self.camera = Camera(int(self.rect.width), int(self.rect.height))

        # Colors
        self.bg_color = (0, 0, 0)
        self.border_color = (200, 200, 200)
        self.terrain_color = (255, 255, 255)
        self.viewport_color = (128, 128, 128)

        # Fixed world span shown on the minimap (independent of main camera zoom)
        # Horizontal span in world units
        self.world_span_x = 20000.0

    def _terrain_resolution(self, lod: int) -> float:
        get_resolution = getattr(self.terrain, "get_resolution", None)
        if callable(get_resolution):
            try:
                return max(1e-6, float(get_resolution(lod)))
            except Exception:
                return 2.0
        return 2.0

    def _pick_lod_for_world_step(self, world_step: float, max_lod: int = 8) -> int:
        target = max(1e-6, float(world_step))
        import math as _math

        best_lod = 0
        best_score = float("inf")
        for lod in range(max(0, int(max_lod)) + 1):
            res = self._terrain_resolution(lod)
            score = abs(_math.log2(res / target))
            if score < best_score:
                best_lod = lod
                best_score = score
        return best_lod

    def draw(
        self,
        screen: pygame.Surface,
        main_camera: Camera,
        height_scale: float,
        contacts=None,
        sites=None,
    ):
        """Draw minimap showing terrain overview and viewport indicator.

        Args:
            screen: Pygame surface to draw on
            main_camera: Main camera (to show viewport indicator)
            height_scale: Vertical scale for terrain height
        """
        # Draw background and border
        minimap_rect = self.rect.to_pygame_rect()
        pygame.draw.rect(screen, self.bg_color, minimap_rect)
        pygame.draw.rect(screen, self.border_color, minimap_rect, 2)

        # Get main camera viewport bounds (used later for viewport box only)
        visible = main_camera.get_visible_world_rect()
        cam_min_x = visible.min_x
        cam_max_x = visible.max_x
        cam_min_y = visible.min_y
        cam_max_y = visible.max_y

        # Configure minimap camera to show a fixed world span centered on the main camera
        minimap_world_width = self.world_span_x
        # Choose a generous vertical span based on terrain amplitude and aspect ratio
        aspect = self.rect.height / self.rect.width if self.rect.width > 0 else 1.0
        # Estimate vertical span based on a generous constant if amplitude missing
        terrain_span_y = getattr(self.terrain, "amplitude", 5000.0) * 2.5 * height_scale
        minimap_world_height = max(terrain_span_y, minimap_world_width * aspect)

        # Center minimap camera on main camera position
        self.camera.x = main_camera.x
        self.camera.y = main_camera.y

        # Set zoom to fit the minimap world bounds
        self.camera.zoom = min(
            self.rect.width / minimap_world_width, self.rect.height / minimap_world_height
        )

        # Get terrain points for minimap (stable world-grid sampling)
        minimap_visible = self.camera.get_visible_world_rect()
        world_span = minimap_visible.width
        desired_step = world_span / 80.0
        lod = self._pick_lod_for_world_step(desired_step)
        world_step = max(desired_step, self._terrain_resolution(lod))
        import math as _math

        start_world_x = _math.floor(minimap_visible.min_x / world_step) * world_step
        end_world_x = minimap_visible.max_x + world_step

        minimap_points = []
        wx = start_world_x

        # Build an offset camera that maps directly to absolute screen pixels
        oc = OffsetCamera(
            self.camera.x,
            self.camera.y,
            self.camera.zoom,
            self.rect.x + self.rect.width / 2.0,
            self.rect.y + self.rect.height / 2.0,
        )

        profile_fn = getattr(self.terrain, "profile", None)
        if callable(profile_fn):
            samples = profile_fn(
                minimap_visible.min_x,
                minimap_visible.max_x + world_step,
                lod=lod,
                step=world_step,
            )
        else:
            samples = []
            while wx <= end_world_x:
                samples.append((wx, self.terrain(wx, lod=lod)))
                wx += world_step

        for wx, wy in samples:
            minimap_pt = oc.world_to_screen(Vector2(wx, wy * height_scale))
            minimap_pt = self.rect.clamp_point(minimap_pt)
            minimap_points.append((minimap_pt.x, minimap_pt.y))

        # Draw terrain
        if len(minimap_points) >= 2:
            pygame.draw.aalines(screen, self.terrain_color, False, minimap_points)

        # Draw viewport indicator using minimap camera
        # Convert main camera bounds to minimap screen coordinates
        viewport_corners = [
            (cam_min_x, cam_min_y),
            (cam_max_x, cam_min_y),
            (cam_max_x, cam_max_y),
            (cam_min_x, cam_max_y),
        ]

        minimap_viewport_corners = []
        for world_x, world_y in viewport_corners:
            minimap_pt = oc.world_to_screen(Vector2(world_x, world_y))
            minimap_pt = self.rect.clamp_point(minimap_pt)
            minimap_viewport_corners.append((minimap_pt.x, minimap_pt.y))

        # Draw viewport rectangle
        if len(minimap_viewport_corners) == 4:
            pygame.draw.lines(
                screen, self.viewport_color, True, minimap_viewport_corners, 2
            )

        # Draw landing-site markers.
        if sites is not None and hasattr(sites, "get_sites"):
            span = Range1D.from_center(self.camera.x, self.world_span_x / 2.0)
            for s in sites.get_sites(span):
                world_y = s.y * height_scale
                pt = oc.world_to_screen(Vector2(s.x, world_y))
                pt = self.rect.clamp_point(pt)
                info = getattr(s, "info", None) or {}
                color = (255, 255, 0) if info.get("award", 1) == 0 else (50, 255, 50)
                pygame.draw.rect(
                    screen,
                    color,
                    pygame.Rect(int(pt.x) - 2, int(pt.y) - 2, 4, 4),
                )
            return

        # Fallback: radar contacts (older call sites)
        if contacts:
            for c in contacts:
                if c.x is None or c.y is None:
                    continue
                world_y = c.y * height_scale
                pt = oc.world_to_screen(Vector2(c.x, world_y))
                pt = self.rect.clamp_point(pt)
                award = 1 if not c.info else c.info.get("award", 1)
                color = (255, 255, 0) if award == 0 else (50, 255, 50)
                pygame.draw.rect(
                    screen,
                    color,
                    pygame.Rect(int(pt.x) - 2, int(pt.y) - 2, 4, 4),
                )
