"""Camera system for moveable and zoomable viewport."""

from core.maths import Rect, Vector2
from core.components import Transform

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

        # Camera transform (position + rotation, though rotation unused for now)
        self.trans = Transform()
        
        # Zoom level (pixels per world unit)
        self.zoom = 2.0
        self.min_zoom = 0.02
        self.max_zoom = 2.0

        # Movement speed
        self.pan_speed = 5.0
        self.zoom_speed = 1.1

    @property
    def x(self) -> float:
        return self.trans.x
    
    @x.setter
    def x(self, value: float):
        self.trans.x = value

    @property
    def y(self) -> float:
        return self.trans.y
    
    @y.setter
    def y(self, value: float):
        self.trans.y = value

    def world_to_screen(self, pos: Vector2) -> Vector2:
        """Convert world coordinates to screen pixel coordinates."""
        screen_x = (pos.x - self.x) * self.zoom + self.screen_width / 2
        # Invert Y: world y-up -> screen y-down
        screen_y = (self.y - pos.y) * self.zoom + self.screen_height / 2
        return Vector2(screen_x, screen_y)

    def screen_to_world(self, pos: Vector2) -> Vector2:
        """Convert screen pixel coordinates to world coordinates."""
        world_x = (pos.x - self.screen_width / 2) / self.zoom + self.x
        # Invert Y back to world
        world_y = self.y - (pos.y - self.screen_height / 2) / self.zoom
        return Vector2(world_x, world_y)

    def get_visible_world_rect(self) -> Rect:
        """Get world-space axis-aligned view bounds."""
        top_left = self.screen_to_world(Vector2(0.0, 0.0))
        bottom_right = self.screen_to_world(
            Vector2(float(self.screen_width), float(self.screen_height))
        )
        return Rect.from_bounds(top_left.x, bottom_right.x, bottom_right.y, top_left.y)

    def pan(self, delta: Vector2):
        """Move camera by given amount in world coordinates."""
        self.x += delta.x
        self.y += delta.y

    def zoom_at(self, screen_pos: Vector2, factor: float):
        """Zoom in/out at a specific screen position (keeps point under cursor fixed).

        Args:
            screen_pos: Screen coordinate to zoom towards
            factor: Zoom multiplier (>1 = zoom in, <1 = zoom out)
        """
        # Get world position before zoom
        world_pos = self.screen_to_world(screen_pos)

        # Apply zoom
        self.zoom *= factor
        self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom))  # Clamp zoom

        # Adjust camera position to keep world point under cursor
        new_world_pos = self.screen_to_world(screen_pos)
        self.x += world_pos.x - new_world_pos.x
        self.y += world_pos.y - new_world_pos.y

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
            self.pan(Vector2(-move_amount, 0.0))
        if signals.get("pan_right"):
            self.pan(Vector2(move_amount, 0.0))
        if signals.get("pan_up"):
            self.pan(Vector2(0.0, move_amount))
        if signals.get("pan_down"):
            self.pan(Vector2(0.0, -move_amount))

        # Zoom via keyboard at screen center
        if signals.get("zoom_in") or signals.get("zoom_out"):
            cx = self.screen_width // 2
            cy = self.screen_height // 2
            if signals.get("zoom_in"):
                self.zoom_at(Vector2(cx, cy), self.zoom_speed)
            if signals.get("zoom_out"):
                self.zoom_at(Vector2(cx, cy), 1.0 / self.zoom_speed)


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

    def world_to_screen(self, pos: Vector2) -> Vector2:
        sx = int(self._px + (pos.x - self.x) * self.zoom)
        # Invert Y for sub-viewports as well
        sy = int(self._py + (self.y - pos.y) * self.zoom)
        return Vector2(sx, sy)
