"""Centralized configuration constants."""

# Screen defaults
DEFAULT_SCREEN_WIDTH = 640
DEFAULT_SCREEN_HEIGHT = 480
DEFAULT_WINDOW_SCALE = 2  # Desktop: render at design res, display at Nx (e.g. 1280x960)

# Update rates
TARGET_RENDERING_FPS = 60
PHYSICS_FPS = 120
BOT_FPS = 60

# Physics
GRAVITY = -9.8
GRAVITY_MAG = abs(float(GRAVITY))
