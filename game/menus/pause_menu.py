"""Pause menu overlay for the game."""

from __future__ import annotations

from enum import StrEnum

import pygame

from game.game_state import PauseReason


class MenuAction(StrEnum):
    RESUME = "resume"
    RESTART = "restart"
    QUIT_TO_TITLE = "quit_to_title"


class PauseMenu:
    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.font = pygame.font.SysFont("monospace", 60, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 40)
        self.selected_index = 0
        self._items: list[tuple[str, MenuAction]] = []
        self._reason: PauseReason | None = None
        self._overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)

    def configure(self, reason: PauseReason) -> None:
        """Set up menu items for the given pause reason."""
        self._reason = reason
        self.selected_index = 0
        if reason == PauseReason.CRASHED:
            self._items = [
                ("RESTART", MenuAction.RESTART),
                ("QUIT TO TITLE", MenuAction.QUIT_TO_TITLE),
            ]
        else:
            self._items = [
                ("RESUME", MenuAction.RESUME),
                ("RESTART", MenuAction.RESTART),
                ("QUIT TO TITLE", MenuAction.QUIT_TO_TITLE),
            ]

    def handle_event(self, event: pygame.event.Event) -> MenuAction | None:
        """Process a single pygame event. Returns action if selected, None otherwise."""
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.selected_index = (self.selected_index - 1) % len(self._items)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.selected_index = (self.selected_index + 1) % len(self._items)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self._items[self.selected_index][1]
            elif event.key == pygame.K_ESCAPE:
                for _, action in self._items:
                    if action == MenuAction.RESUME:
                        return MenuAction.RESUME
                return self._items[0][1]
        return None

    def draw(self) -> None:
        """Render pause menu overlay on top of existing frame."""
        self._overlay.fill((0, 0, 0, 180))
        self.screen.blit(self._overlay, (0, 0))

        if self._reason == PauseReason.CRASHED:
            title = "CRASHED"
            title_color = (255, 80, 80)
        else:
            title = "PAUSED"
            title_color = (160, 160, 170)

        cx = self.screen.get_width() // 2
        cy = self.screen.get_height() // 2

        # Measure content: title height + gap + items
        title_surf = self.font.render(title, True, title_color)
        title_h = title_surf.get_height()
        gap = 36
        item_h = self.font_small.get_height() + 20
        content_h = title_h + gap + len(self._items) * item_h

        # Box wraps content with padding
        pad_top, pad_bottom = 48, 48
        box_w = 580
        box_h = pad_top + content_h + pad_bottom

        # Center the box on screen
        box_rect = pygame.Rect(cx - box_w // 2, cy - box_h // 2, box_w, box_h)

        # Semi-transparent box background
        box_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        box_surf.fill((40, 40, 40, 128))
        self.screen.blit(box_surf, box_rect.topleft)
        pygame.draw.rect(self.screen, (80, 80, 90), box_rect, 2)

        # Title: first element of the centered content block
        title_rect = title_surf.get_rect(centerx=cx, top=box_rect.top + pad_top)
        self.screen.blit(title_surf, title_rect)

        # Items: below title + gap
        y = title_rect.bottom + gap
        for i, (label, _) in enumerate(self._items):
            selected = i == self.selected_index
            color = (50, 255, 50) if selected else (180, 180, 180)
            prefix = "> " if selected else "  "

            item_surf = self.font_small.render(f"{prefix}{label}", True, color)
            item_rect = item_surf.get_rect(centerx=cx, top=y)
            self.screen.blit(item_surf, item_rect)
            y += item_h
