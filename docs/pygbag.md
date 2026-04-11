# Web Build (pygbag)

This document describes the browser-playable web build using pygbag.

## Architecture

The web build uses a dedicated `pygbag/` entrypoint that bypasses `main.py` and the full CLI to avoid importing `bot_framework`, `tooling/`, and `app/` at module load time.

### Key design decisions

1. **Separate entrypoint**: `pygbag/__init__.py` provides `run_web_interactive()` which is called by pygbag's JavaScript glue code.

2. **No bot/tooling imports**: The web entrypoint only imports from `game/` and standard library modules. `bot_framework` is never loaded.

3. **Browser-safe rendering**: `game/ui/renderer.py` detects the browser environment via `sys.emscripten` and avoids desktop-specific SDL environment variables.

4. **No-bot runtime**: `NoBotRuntimeAdapter` is used since bots require `cvxpy` which is not trivially compiled to WebAssembly.

## Scope (v1)

- **Supported**: Interactive gameplay on `flat` level
- **Supported (low-risk)**: Interactive gameplay on `mountains` level  
- **Not supported**: Bots, headless evaluation, benchmark/report tooling

## File structure

```
pygbag/
└── __init__.py          # Web entrypoint (run_web_interactive, main, WebGame)
```

The `pygbag/__init__.py` module provides:
- `EMSCRIPTEN` constant: True when running under emscripten
- `is_browser()`: Returns True in browser environments
- `run_web_interactive()`: Main entrypoint for browser gameplay
- `build_web_game()`: Builds a minimal WebGame instance for browser play
- `WebGame`: Minimal game class that avoids bot_framework imports

## Build requirements

pygbag requires:
1. Python 3.13+ compiled to WebAssembly via emscripten
2. pygame-ce compiled to WebAssembly
3. All game dependencies compiled to WebAssembly or available as pure Python

## Build workflow

```bash
# Install pygbag (requires emscripten toolchain)
pip install pygbag

# Build the web app
pygbag --dir . --name pylander --app-ttl 300

# Serve locally for testing
cd build/pylander
python -m http.server 8080
```

The build output goes to `build/pylander/` with:
- `index.html` - JavaScript loader
- `pylander.data`, `pylander.js`, `pylander.wasm` - compiled Python

## Running

Open `build/pylander/index.html` in a browser, or serve via http server.

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
