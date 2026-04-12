"""Title screen with level selection menu."""

from __future__ import annotations

import pygame


class TitleScreen:
    def __init__(self, screen: pygame.Surface):
        """Initialize with the target rendering surface."""
        self.screen = screen
        self.font_large = pygame.font.SysFont("monospace", 56, bold=True)
        self.font_medium = pygame.font.SysFont("monospace", 28)
        self.font_small = pygame.font.SysFont("monospace", 18)
        self.selected_index = 0
        self.levels = [
            {
                "key": "flat",
                "name": "Flat Plains",
                "desc": "Gentle terrain, beginner friendly",
            },
            {
                "key": "mountains",
                "name": "Mountains",
                "desc": "Steep terrain with elevated pads",
            },
        ]

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process a single pygame event. Returns level key if selected, None otherwise."""
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.selected_index = (self.selected_index - 1) % len(self.levels)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.selected_index = (self.selected_index + 1) % len(self.levels)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self.levels[self.selected_index]["key"]
        return None

    def draw(self) -> None:
        """Render the title screen to self.screen."""
        self.screen.fill((20, 20, 25))

        cx = self.screen.get_width() // 2
        cy = self.screen.get_height() // 2

        # Measure all content as one block
        title_surf = self.font_large.render("PYLANDER", True, (220, 220, 220))
        title_h = title_surf.get_height()

        gap = 60
        item_spacing = 24
        item_h = (
            self.font_medium.get_height() + self.font_small.get_height() + item_spacing
        )
        content_h = title_h + gap + len(self.levels) * item_h

        # Center the content block vertically
        content_top = cy - content_h // 2

        # Title
        title_rect = title_surf.get_rect(centerx=cx, top=content_top)
        self.screen.blit(title_surf, title_rect)

        # Level items
        y = title_rect.bottom + gap
        for i, level in enumerate(self.levels):
            selected = i == self.selected_index
            prefix = "> " if selected else "  "
            color = (50, 255, 50) if selected else (150, 150, 150)

            name_surf = self.font_medium.render(f"{prefix}{level['name']}", True, color)
            name_rect = name_surf.get_rect(centerx=cx, top=y)
            self.screen.blit(name_surf, name_rect)

            desc_color = (100, 180, 100) if selected else (90, 90, 100)
            desc_surf = self.font_small.render(f"    {level['desc']}", True, desc_color)
            desc_rect = desc_surf.get_rect(
                centerx=cx, top=y + name_surf.get_height() + 2
            )
            self.screen.blit(desc_surf, desc_rect)

            y += item_h

