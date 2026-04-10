"""FPS overlay drawing helper."""

from __future__ import annotations


class FpsOverlay:
    """Render FPS and frame time in the top-right corner."""

    def __init__(self, font, screen, clock):
        self.font = font
        self.screen = screen
        self.clock = clock
        self._cached_label: str | None = None
        self._cached_shadow = None
        self._cached_text = None

    def draw(self) -> None:
        if self.clock is None:
            return
        screen_rect = self.screen.get_rect()
        fps = self.clock.get_fps()
        frame_time = self.clock.get_rawtime()
        label = f"FPS: {fps:.1f}, FT: {frame_time:.2f}ms"
        # Only re-render surfaces when the label text changes
        if label != self._cached_label:
            self._cached_shadow = self.font.render(label, True, (0, 0, 0))
            self._cached_text = self.font.render(label, True, (255, 255, 255))
            self._cached_label = label
        x = screen_rect.right - self._cached_text.get_width() - 10
        y = 10
        self.screen.blit(self._cached_shadow, (x + 1, y + 1))
        self.screen.blit(self._cached_text, (x, y))
