"""Interactive Pygame viewer for testing levels (terrain + landing sites).

Controls:
  - Mouse: Left-drag to pan, wheel to zoom at cursor
  - R: Reset camera
  - Q / ESC: Quit
"""

import sys
import pygame

from core.components import Transform
from core.maths import Range1D, Vector2
from ui.camera import Camera
from levels import create_level, list_available_levels


def _require_component(entity, component_type):
    comp = entity.get_component(component_type)
    if comp is None:
        raise RuntimeError(f"Entity {entity.uid} missing component {component_type.__name__}")
    return comp


class LevelViewer:
    def __init__(
        self, level_name: str | None = None, width: int = 1280, height: int = 720
    ):
        pygame.init()
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("Level Viewer")
        self.clock = pygame.time.Clock()
        self.camera = Camera(width, height)

        # Level setup (defaults to first available level if none provided)
        if level_name is None:
            available = list_available_levels()
            level_name = available[0] if available else None
        if level_name is None:
            raise RuntimeError("No levels available")
        self.level = create_level(level_name)

        # Minimal game-like container to host level
        class _StubGame:
            pass

        self.game = _StubGame()
        self.level.setup(self.game, seed=0)
        self.terrain = self.level.world.terrain
        self.sites = self.level.world.sites
        # Center camera near start
        trans = _require_component(self.level.world.lander, Transform)
        self.camera.x = trans.pos.x
        self.camera.y = trans.pos.y

        # Colors
        self.bg = (20, 20, 25)
        self.terrain_color = (230, 230, 230)
        self.target_color = (50, 255, 50)
        self.text_color = (210, 210, 210)

        # Fonts
        self.font = pygame.font.SysFont("monospace", 14)

        # Interaction state
        self.dragging = False
        self.last_mouse = (0, 0)

        # Rendering settings
        self.height_scale = 1.0
        self.target_segments = 60  # desired number of segments across screen

    def _lod_for_zoom(self) -> int:
        z = self.camera.zoom
        if z >= 1.0:
            return 0
        if z >= 0.5:
            return 1
        if z >= 0.25:
            return 2
        return 3

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    return False
                if event.key == pygame.K_r:
                    self.camera.x = 0.0
                    self.camera.y = 0.0
                    self.camera.zoom = 2.0
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.dragging = True
                    self.last_mouse = event.pos
                elif event.button == 4:  # wheel up
                    mx, my = event.pos
                    self.camera.zoom_at(Vector2(mx, my), self.camera.zoom_speed)
                elif event.button == 5:  # wheel down
                    mx, my = event.pos
                    self.camera.zoom_at(Vector2(mx, my), 1.0 / self.camera.zoom_speed)
            if event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self.dragging = False
            if event.type == pygame.MOUSEMOTION and self.dragging:
                mx, my = event.pos
                dx = mx - self.last_mouse[0]
                dy = my - self.last_mouse[1]
                self.last_mouse = (mx, my)
                # Convert pixel delta to world delta (invert Y for world up)
                self.camera.pan(Vector2(-dx / self.camera.zoom, dy / self.camera.zoom))
        return True

    def draw_terrain(self):
        visible = self.camera.get_visible_world_rect()
        world_span = visible.width

        lod = self._lod_for_zoom()
        base_interval = self.terrain.get_resolution(lod)
        world_step = max(world_span / self.target_segments, base_interval)

        # Anchor to a world grid so the polyline slides smoothly when panning
        import math as _math

        start_world_x = _math.floor(visible.min_x / world_step) * world_step
        end_world_x = visible.max_x + world_step

        pts = []
        wx = start_world_x
        while wx <= end_world_x:
            world_y = self.terrain(wx, lod)
            sx, sy = self.camera.world_to_screen(Vector2(wx, world_y * self.height_scale))
            pts.append((sx, sy))
            wx += world_step

        if len(pts) >= 2:
            pygame.draw.lines(self.screen, self.terrain_color, False, pts)

    def draw_sites(self):
        visible = self.camera.get_visible_world_rect()
        site_views = self.sites.get_sites(Range1D(visible.min_x, visible.max_x))
        for site in site_views:
            tx = site.x
            ty = site.y
            ts = site.size
            sx0, sy0 = self.camera.world_to_screen(
                Vector2(tx - ts / 2, ty * self.height_scale)
            )
            sx1, sy1 = self.camera.world_to_screen(
                Vector2(tx + ts / 2, ty * self.height_scale)
            )
            pygame.draw.line(self.screen, self.target_color, (sx0, sy0), (sx1, sy1), 3)

    def draw_hud(self):
        visible = self.camera.get_visible_world_rect()
        info = (
            f"cam=({self.camera.x:.1f}, {self.camera.y:.1f}) "
            f"size=({visible.width:.1f}, {visible.height:.1f}) "
            f"zoom={self.camera.zoom:.3f} lod={self._lod_for_zoom()}"
        )
        txt = self.font.render(info, True, self.text_color)
        self.screen.blit(txt, (10, 10))

        controls = "LMB drag: pan  |  Wheel: zoom  |  R: reset  |  Q/ESC: quit"
        txt2 = self.font.render(controls, True, self.text_color)
        self.screen.blit(txt2, (10, 30))

    def draw_axes(self):
        w = self.screen.get_width()
        h = self.screen.get_height()
        cx0, cy0 = self.camera.world_to_screen(Vector2(0.0, 0.0))
        pygame.draw.line(self.screen, (80, 80, 100), (0, cy0), (w, cy0), 1)
        pygame.draw.line(self.screen, (100, 80, 80), (cx0, 0), (cx0, h), 1)

    def draw(self):
        self.screen.fill(self.bg)
        self.draw_axes()
        self.draw_terrain()
        self.draw_sites()
        self.draw_hud()
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            running = self.handle_events()
            self.draw()
            self.clock.tick(120)


def main():
    # Optional level name as first arg
    args = sys.argv[1:]
    level_name = args[0] if args else None
    viewer = LevelViewer(level_name)
    viewer.run()


if __name__ == "__main__":
    main()
