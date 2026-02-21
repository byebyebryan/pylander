"""HUD overlay rendering for UI text."""

from __future__ import annotations


class HudOverlay:
    """Draw heads-up display text for lander status and controls."""

    def __init__(self, font, screen, bot=None):
        self.font = font
        self.screen = screen
        self.bot = bot

    def draw(self, level, bot=None) -> None:
        lander = level.lander
        if not lander:
            return

        # Caller can pass a bot override; fall back to the stored reference
        effective_bot = bot if bot is not None else self.bot

        info_lines = self._build_info_lines(level, effective_bot)
        self._draw_text_lines(info_lines, 10, (220, 220, 220))

        control_lines = self._build_control_lines(lander)
        y_offset = self.screen.get_height() - 20 - (len(control_lines) * 18)
        self._draw_text_lines(control_lines, y_offset, (200, 200, 200))

    def _build_info_lines(self, level, bot=None) -> list[str]:
        lines: list[str] = [f"CREDITS: {level.lander.credits:.0f}"]
        lines.extend(level.lander.get_stats_text(level.terrain))
        if bot is not None and hasattr(bot, "get_stats_text"):
            lines.extend(bot.get_stats_text())
        return lines

    def _build_control_lines(self, lander) -> list[str]:
        if lander and hasattr(lander, "get_controls_text"):
            return lander.get_controls_text()
        return [
            "Controls:",
            "W/UP: Increase thrust",
            "S/DOWN: Decrease thrust",
            "A/LEFT: Rotate left",
            "D/RIGHT: Rotate right",
            "F: Refuel (when landed)",
            "R: Reset",
            "Q/ESC: Quit",
        ]

    def _draw_text_lines(self, lines: list[str], y_offset: int, color) -> None:
        for line in lines:
            if line:
                shadow = self.font.render(line, True, (0, 0, 0))
                self.screen.blit(shadow, (11, y_offset + 1))
                text_surface = self.font.render(line, True, color)
                self.screen.blit(text_surface, (10, y_offset))
            y_offset += 18
