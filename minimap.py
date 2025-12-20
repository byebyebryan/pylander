"""Minimap display showing camera position and terrain overview."""

import pygame
from camera import Camera, OffsetCamera


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
        self.width = int(screen_width * minimap_scale)
        self.height = int(screen_height * minimap_scale)
        self.margin = 10

        # Position (top-right corner)
        self.x = screen_width - self.width - self.margin
        self.y = self.margin

        # Minimap has its own camera for coordinate transforms
        self.camera = Camera(self.width, self.height)

        # Colors
        self.bg_color = (0, 0, 0)
        self.border_color = (200, 200, 200)
        self.terrain_color = (255, 255, 255)
        self.viewport_color = (128, 128, 128)

        # Fixed world span shown on the minimap (independent of main camera zoom)
        # Horizontal span in world units
        self.world_span_x = 20000.0

    def draw(
        self,
        screen: pygame.Surface,
        main_camera: Camera,
        height_scale: float,
        contacts=None,
    ):
        """Draw minimap showing terrain overview and viewport indicator.

        Args:
            screen: Pygame surface to draw on
            main_camera: Main camera (to show viewport indicator)
            height_scale: Vertical scale for terrain height
        """
        # Draw background and border
        minimap_rect = pygame.Rect(self.x, self.y, self.width, self.height)
        pygame.draw.rect(screen, self.bg_color, minimap_rect)
        pygame.draw.rect(screen, self.border_color, minimap_rect, 2)

        # Get main camera viewport bounds (used later for viewport box only)
        cam_min_x, cam_max_x, cam_min_y, cam_max_y = (
            main_camera.get_visible_world_bounds()
        )

        # Configure minimap camera to show a fixed world span centered on the main camera
        minimap_world_width = self.world_span_x
        # Choose a generous vertical span based on terrain amplitude and aspect ratio
        aspect = self.height / self.width if self.width > 0 else 1.0
        # Estimate vertical span based on a generous constant if amplitude missing
        terrain_span_y = getattr(self.terrain, "amplitude", 5000.0) * 2.5 * height_scale
        minimap_world_height = max(terrain_span_y, minimap_world_width * aspect)

        # Center minimap camera on main camera position
        self.camera.x = main_camera.x
        self.camera.y = main_camera.y

        # Set zoom to fit the minimap world bounds
        self.camera.zoom = min(
            self.width / minimap_world_width, self.height / minimap_world_height
        )

        # Get terrain points for minimap (stable world-grid sampling)
        minimap_min_x, minimap_max_x, _, _ = self.camera.get_visible_world_bounds()
        world_span = minimap_max_x - minimap_min_x
        world_step = max(world_span / 80.0, 1.0)
        import math as _math

        start_world_x = _math.floor(minimap_min_x / world_step) * world_step
        end_world_x = minimap_max_x + world_step

        minimap_points = []
        wx = start_world_x
        # Choose a conservative LOD for minimap to keep it light
        # Based on minimap camera zoom
        z = self.camera.zoom
        if z >= 1.0:
            lod = 1
        elif z >= 0.5:
            lod = 2
        else:
            lod = 3

        # Build an offset camera that maps directly to absolute screen pixels
        oc = OffsetCamera(
            self.camera.x,
            self.camera.y,
            self.camera.zoom,
            self.x + self.width / 2,
            self.y + self.height / 2,
        )

        while wx <= end_world_x:
            world_y = self.terrain(wx, lod=lod) * height_scale
            minimap_px, minimap_py = oc.world_to_screen(wx, world_y)
            minimap_px = max(self.x, min(self.x + self.width, minimap_px))
            minimap_py = max(self.y, min(self.y + self.height, minimap_py))
            minimap_points.append((minimap_px, minimap_py))
            wx += world_step

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
            minimap_px, minimap_py = oc.world_to_screen(world_x, world_y)
            # Clamp to minimap bounds
            minimap_px = max(self.x, min(self.x + self.width, minimap_px))
            minimap_py = max(self.y, min(self.y + self.height, minimap_py))
            minimap_viewport_corners.append((minimap_px, minimap_py))

        # Draw viewport rectangle
        if len(minimap_viewport_corners) == 4:
            pygame.draw.lines(
                screen, self.viewport_color, True, minimap_viewport_corners, 2
            )

        # Draw landing pad markers using provided radar contacts as fixed 2x2 squares
        if contacts:
            for c in contacts:
                if c.distance is None:
                    break
                world_y = c.y * height_scale
                px, py = oc.world_to_screen(c.x, world_y)
                px = max(self.x, min(self.x + self.width, px))
                py = max(self.y, min(self.y + self.height, py))
                color = (255, 255, 0) if c.info["award"] == 0 else (50, 255, 50)
                pygame.draw.rect(screen, color, pygame.Rect(px - 2, py - 2, 4, 4))
