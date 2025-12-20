"""FPS overlay drawing helper."""

from __future__ import annotations


class FpsOverlay:
    """Render FPS and frame time in the top-right corner."""

    def __init__(self, font, screen, clock):
        self.font = font
        self.screen = screen
        self.clock = clock

    def draw(self) -> None:
        if self.clock is None:
            return
        fps = self.clock.get_fps()
        frame_time = self.clock.get_rawtime()
        label = f"FPS: {fps:.1f}, FT: {frame_time:.2f}ms"
        text_surface = self.font.render(label, True, (0, 0, 0))
        x = self.screen.get_width() - text_surface.get_width() - 10
        y = 10
        self.screen.blit(text_surface, (x + 1, y + 1))
        text_surface = self.font.render(label, True, (255, 255, 255))
        self.screen.blit(text_surface, (x, y))
