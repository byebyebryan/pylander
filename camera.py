"""Camera system for moveable and zoomable viewport."""


class Camera:
    """2D camera with pan and zoom for world-to-screen coordinate mapping."""

    def __init__(self, screen_width: int, screen_height: int):
        """Initialize camera centered on world origin.

        Args:
            screen_width: Width of the display in pixels
            screen_height: Height of the display in pixels
        """
        self.screen_width = screen_width
        self.screen_height = screen_height

        # Camera position in world coordinates (center point)
        self.x = 0.0
        self.y = 0.0

        # Zoom level (pixels per world unit)
        self.zoom = 2.0
        self.min_zoom = 0.02
        self.max_zoom = 2.0

        # Movement speed
        self.pan_speed = 5.0
        self.zoom_speed = 1.1

    def world_to_screen(self, world_x: float, world_y: float) -> tuple[float, float]:
        """Convert world coordinates to screen pixel coordinates.

        Args:
            world_x: X coordinate in world space
            world_y: Y coordinate in world space

        Returns:
            (screen_x, screen_y) tuple in pixels
        """
        screen_x = (world_x - self.x) * self.zoom + self.screen_width / 2
        # Invert Y: world y-up -> screen y-down
        screen_y = (self.y - world_y) * self.zoom + self.screen_height / 2
        return screen_x, screen_y

    def screen_to_world(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        """Convert screen pixel coordinates to world coordinates.

        Args:
            screen_x: X coordinate in pixels
            screen_y: Y coordinate in pixels

        Returns:
            (world_x, world_y) tuple
        """
        world_x = (screen_x - self.screen_width / 2) / self.zoom + self.x
        # Invert Y back to world
        world_y = self.y - (screen_y - self.screen_height / 2) / self.zoom
        return world_x, world_y

    def get_visible_world_bounds(self) -> tuple[float, float, float, float]:
        """Get the world coordinate bounds currently visible on screen.

        Returns:
            (min_x, max_x, min_y, max_y) in world coordinates
        """
        top_left = self.screen_to_world(0, 0)
        bottom_right = self.screen_to_world(self.screen_width, self.screen_height)
        return top_left[0], bottom_right[0], top_left[1], bottom_right[1]

    def pan(self, dx: float, dy: float):
        """Move camera by given amount in world coordinates.

        Args:
            dx: Change in x position
            dy: Change in y position
        """
        self.x += dx
        self.y += dy

    def zoom_at(self, screen_x: float, screen_y: float, factor: float):
        """Zoom in/out at a specific screen position (keeps point under cursor fixed).

        Args:
            screen_x: Screen x coordinate to zoom towards
            screen_y: Screen y coordinate to zoom towards
            factor: Zoom multiplier (>1 = zoom in, <1 = zoom out)
        """
        # Get world position before zoom
        world_x, world_y = self.screen_to_world(screen_x, screen_y)

        # Apply zoom
        self.zoom *= factor
        self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom))  # Clamp zoom

        # Adjust camera position to keep world point under cursor
        new_world_x, new_world_y = self.screen_to_world(screen_x, screen_y)
        self.x += world_x - new_world_x
        self.y += world_y - new_world_y

    # Camera should not own input; movement is controlled by InputHandler

    def handle_input(self, signals: dict, dt: float):
        """Apply key-based pan/zoom using provided signals.

        Pan keys: pan_left/right/up/down; Zoom keys: zoom_in/zoom_out.
        Zooms around screen center.
        """
        # Reset camera to defaults when requested
        if signals.get("reset"):
            self.x = 0.0
            self.y = 0.0
            self.zoom = 2.0

        move_amount = self.pan_speed * dt / max(0.01, self.zoom)
        if signals.get("pan_left"):
            self.pan(-move_amount, 0)
        if signals.get("pan_right"):
            self.pan(move_amount, 0)
        if signals.get("pan_up"):
            self.pan(0, move_amount)
        if signals.get("pan_down"):
            self.pan(0, -move_amount)

        # Zoom via keyboard at screen center
        if signals.get("zoom_in") or signals.get("zoom_out"):
            cx = self.screen_width // 2
            cy = self.screen_height // 2
            if signals.get("zoom_in"):
                self.zoom_at(cx, cy, self.zoom_speed)
            if signals.get("zoom_out"):
                self.zoom_at(cx, cy, 1.0 / self.zoom_speed)


class OffsetCamera:
    """Lightweight camera that maps world coordinates to absolute screen pixels
    using a provided pixel center and scale.

    This is useful for drawing into sub-rectangles (viewports) like minimaps or
    orientation insets without modifying global camera state.
    """

    def __init__(
        self,
        center_x: float,
        center_y: float,
        pixels_per_world: float,
        pixel_center_x: float,
        pixel_center_y: float,
    ):
        self.x = center_x
        self.y = center_y
        self.zoom = pixels_per_world
        self._px = pixel_center_x
        self._py = pixel_center_y

    def world_to_screen(self, world_x: float, world_y: float) -> tuple[int, int]:
        sx = int(self._px + (world_x - self.x) * self.zoom)
        # Invert Y for sub-viewports as well
        sy = int(self._py + (self.y - world_y) * self.zoom)
        return sx, sy
