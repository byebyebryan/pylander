"""Game state machine: TITLE → PLAYING → PAUSED.

GameHost owns pygame lifecycle and delegates per-state logic to menu
renderers and game sessions.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Protocol

import pygame

from game.game_state import GameState, PauseReason
from game.menus.pause_menu import MenuAction, PauseMenu
from game.menus.title_screen import TitleScreen

if TYPE_CHECKING:
    pass


class GameSession(Protocol):
    """Interface for game sessions driven by GameHost."""

    def tick(self, *, external_events: list | None = None) -> dict:
        """One frame. Returns {'running': bool, 'actor_state': str}."""
        ...

    def reset_actor(self) -> None:
        """Reset actor to start, keep world."""
        ...

    @property
    def renderer(self):
        """Return the Renderer, or None for headless."""
        ...


class GameHost:
    """State machine that drives TITLE → PLAYING → PAUSED flow.

    Args:
        session_factory: Callable(level_name: str, seed: int, width: int, height: int) -> GameSession
        skip_title: If True, start at PLAYING with level_name
        level_name: Level to use when skip_title=True
        seed: Random seed (random if None)
        width, height: Screen dimensions
        target_fps: Target frame rate
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[str, int, int, int], GameSession],
        skip_title: bool = False,
        level_name: str | None = None,
        seed: int | None = None,
        width: int = 640,
        height: int = 480,
        window_scale: int = 1,
        target_fps: int = 60,
    ):
        self._session_factory = session_factory
        self._skip_title = skip_title
        self._initial_level_name = level_name or "flat"
        self._seed = seed if seed is not None else random.randint(0, 1_000_000)
        self._width = width
        self._height = height
        self._window_scale = max(1, window_scale)
        self._target_fps = target_fps

        window_w = width * self._window_scale
        window_h = height * self._window_scale

        pygame.init()
        self._screen = pygame.display.set_mode((window_w, window_h))
        pygame.display.set_caption("Lunar Lander")
        self._clock = pygame.time.Clock()

        # Open all joysticks so hat/button events appear in the event queue
        # even before a game session (and its InputHandler) is created.
        pygame.joystick.init()
        self._joysticks = [
            pygame.joystick.Joystick(i)
            for i in range(pygame.joystick.get_count())
        ]

        self._state = GameState.PLAYING if skip_title else GameState.TITLE
        self._session: GameSession | None = None
        self._title_screen = TitleScreen(self._screen)
        self._pause_menu = PauseMenu(self._screen)
        self._paused_frame: pygame.Surface | None = None
        self._running = True

        if self._state == GameState.PLAYING:
            self._start_session(self._initial_level_name)

    def _start_session(self, level_name: str) -> None:
        """Create a new game session for the given level."""
        self._session = self._session_factory(
            level_name, self._seed, self._width, self._height
        )
        if self._session.renderer is not None:
            self._pause_menu = PauseMenu(self._session.renderer.screen)

    def _capture_design_surface(self) -> pygame.Surface | None:
        """Snapshot the renderer's design surface for pause overlay."""
        if self._session is not None and self._session.renderer is not None:
            return self._session.renderer.screen.copy()
        return None

    def _present_paused_frame(self) -> None:
        """Blit frozen frame + overlay onto design surface, push to window."""
        renderer = getattr(self._session, "renderer", None) if self._session else None
        design = renderer.screen if renderer else self._screen

        if self._paused_frame is not None:
            design.blit(self._paused_frame, (0, 0))
        self._pause_menu.draw()

        if renderer is not None and hasattr(renderer, "present"):
            renderer.present()
        else:
            pygame.display.flip()

    def tick(self) -> bool:
        """Execute one frame. Returns False if app should exit."""
        if not self._running:
            return False

        if self._state == GameState.TITLE:
            return self._tick_title()
        elif self._state == GameState.PLAYING:
            return self._tick_playing()
        elif self._state == GameState.PAUSED:
            return self._tick_paused()

        return False

    @staticmethod
    def _expand_controller(events: list) -> list:
        """Append synthetic KEYDOWN events for joystick inputs so menus respond to gamepad."""
        extra: list[pygame.event.Event] = []
        for event in events:
            if event.type == pygame.JOYBUTTONDOWN:
                # A(0)→return  B(1)→escape  Y(3)→r
                key = {0: pygame.K_RETURN, 1: pygame.K_ESCAPE, 3: pygame.K_r}.get(event.button)
                if key is not None:
                    extra.append(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))
            elif event.type == pygame.JOYHATMOTION:
                hx, hy = event.value
                if hy > 0:
                    extra.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP,    mod=0, unicode="", scancode=0))
                elif hy < 0:
                    extra.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,  mod=0, unicode="", scancode=0))
                if hx < 0:
                    extra.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT,  mod=0, unicode="", scancode=0))
                elif hx > 0:
                    extra.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0, unicode="", scancode=0))
        return events + extra

    def _tick_title(self) -> bool:
        for event in self._expand_controller(pygame.event.get()):
            if event.type == pygame.QUIT:
                self._running = False
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._running = False
                return False
            level_key = self._title_screen.handle_event(event)
            if level_key is not None:
                self._start_session(level_key)
                self._state = GameState.PLAYING
                return True

        self._title_screen.draw()
        pygame.display.flip()
        self._clock.tick(self._target_fps)
        return True

    def _tick_playing(self) -> bool:
        all_events = pygame.event.get()

        game_events: list[pygame.event.Event] = []
        for event in all_events:
            if event.type == pygame.QUIT:
                self._running = False
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._paused_frame = self._capture_design_surface()
                self._state = GameState.PAUSED
                self._pause_menu.configure(PauseReason.USER_REQUESTED)
                return True
            # B button (gamepad) → pause (same as Escape)
            if event.type == pygame.JOYBUTTONDOWN and event.button == 1:
                self._paused_frame = self._capture_design_surface()
                self._state = GameState.PAUSED
                self._pause_menu.configure(PauseReason.USER_REQUESTED)
                return True
            game_events.append(event)

        if self._session is None:
            self._running = False
            return False

        result = self._session.tick(external_events=game_events)

        if not result.get("running", True):
            self._running = False
            return False

        actor_state = result.get("actor_state", "flying")
        if actor_state == "crashed":
            self._paused_frame = self._capture_design_surface()
            self._state = GameState.PAUSED
            self._pause_menu.configure(PauseReason.CRASHED)
            return True

        return True

    def _tick_paused(self) -> bool:
        for event in self._expand_controller(pygame.event.get()):
            if event.type == pygame.QUIT:
                self._running = False
                return False
            action = self._pause_menu.handle_event(event)
            if action is not None:
                return self._handle_menu_action(action)

        self._present_paused_frame()
        self._clock.tick(self._target_fps)
        return True

    def _handle_menu_action(self, action: MenuAction) -> bool:
        self._paused_frame = None

        if action == MenuAction.RESUME:
            self._state = GameState.PLAYING
            return True

        if action == MenuAction.RESTART:
            if self._session is not None:
                self._session.reset_actor()
            self._state = GameState.PLAYING
            return True

        if action == MenuAction.QUIT_TO_TITLE:
            self._session = None
            window_w = self._width * self._window_scale
            window_h = self._height * self._window_scale
            self._screen = pygame.display.set_mode((window_w, window_h))
            self._title_screen = TitleScreen(self._screen)
            self._pause_menu = PauseMenu(self._screen)
            self._state = GameState.TITLE
            return True

        return True

    def shutdown(self) -> None:
        """Clean up pygame resources."""
        try:
            pygame.quit()
        except Exception:
            pass

    def run(self) -> None:
        """Desktop synchronous main loop."""
        while self.tick():
            pass
        self.shutdown()
