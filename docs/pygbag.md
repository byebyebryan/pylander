# Web Build (pygbag)

This document describes the browser-playable web build using pygbag.

## Architecture

The web build bypasses `main.py` and the full CLI to avoid importing `bot_framework`, `tooling/`, and `app/` at module load time.

### Key design decisions

1. **Separate entrypoint**: `pygbag_main.py` at the project root is the async entry point sourced by the pygbag template. It imports pygame first (so `pygame.math` is registered before game modules load), then delegates to `game/web.py`.

2. **No bot/tooling imports**: `game/web.py` implements a bot-framework-free async game loop using `await asyncio.sleep(0)` each frame. `bot_framework` is never loaded.

3. **Euler physics**: `PYLANDER_PHYSICS=euler` is set before any imports, ensuring the pure-Python Euler backend is used instead of pymunk (which is not available in WASM).

4. **Error overlay**: Unhandled exceptions are caught and displayed in the browser's infobox overlay (red background, traceback text) so crashes are visible without opening devtools.

## File structure

```
pygbag_main.py       # async entry point (must be at project root)
pygbag.ini           # bundle config: excludes bot_framework/, app/, tests, etc.
game/web.py          # bot-framework-free async game loop
web/
  default.tmpl       # custom HTML template
  favicon.png        # game icon
```

## Build requirements

pygbag requires:
1. Python 3.13+ compiled to WebAssembly via emscripten
2. pygame-ce compiled to WebAssembly
3. All game dependencies compiled to WebAssembly or available as pure Python

## Build workflow

```bash
# Install web-build tooling only when needed
uv sync --group web

# Serve locally (builds automatically and starts CDN-proxy testserver)
uv run pygbag --port 8000 --template web/default.tmpl --icon web/favicon.png .
```

The build output goes to `build/web/` with:
- `index.html` - JavaScript loader
- `pylander.data`, `pylander.js`, `pylander.wasm` - compiled Python

The repo includes a `pygbag.ini` that trims the web bundle to the game-only path by
excluding `bot_framework/`, `tooling/`, `app/`, tests, docs, and local outputs.

## Running

Open `build/web/index.html` in a browser, or serve via http server.

The game starts automatically in interactive mode on the `flat` level.

## Controls

Same as desktop:
- `W`/`UP`: Increase thrust
- `S`/`DOWN`: Decrease thrust
- `A`/`LEFT`: Rotate left
- `D`/`RIGHT`: Rotate right
- `I`/`J`/`K`/`L`: Pan camera
- `=`/`PageUp`, `-`/`PageDown`: Zoom camera
- `F`: Refuel (when landed)
- `TAB`: Switch actor
- `T`: Toggle ballistic path
- `R`: Reset
- `Q`/`ESC`: Quit

## Residual limitations (v1)

1. **No bot support**: Bots require cvxpy which is not trivially compiled to WebAssembly. Headless evaluation and benchmark tooling are not available.

2. **Performance**: WebAssembly pygame is slower than native. Physics and rendering may not hit 60fps on lower-end devices.

3. **No persistent state**: No local storage for credits, progress, etc.

4. **No audio**: Audio subsystem not yet adapted for browser.

5. **Fixed resolution**: The game runs at the canvas resolution set by pygbag (typically window size).

6. **Single level at a time**: Level selection UI is not implemented; always starts on `flat`.

7. **No trace/recording**: Trace capture is disabled in browser environment.
