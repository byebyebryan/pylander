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

## Local dev workflow

For day-to-day browser iteration, use pygbag's local server rather than opening
`build/web/index.html` directly from disk.

Recommended workflow:

```bash
# Start or restart the local web server from the repo root
uv run pygbag --port 8000 --template web/default.tmpl --icon web/favicon.png .
```

- Default local URL: `http://127.0.0.1:8000/`
- Pygbag rebuilds `build/web/` as part of the serve flow.
- The generated artifacts to care about are:
  - `build/web/index.html`
  - `build/web/pylander.apk`
  - `build/web/pylander.tar.gz`

### Detached tmux workflow

During active development, keep pygbag running in a detached named tmux session
so browser refreshes and rebuilds are easy to repeat.

Recommended session name:

```bash
tmux new-session -d -s pylander-web \
  'uv run pygbag --port 8000 --template web/default.tmpl --icon web/favicon.png . > /tmp/pygbag-serve.log 2>&1'
```

Useful follow-ups:

```bash
# Inspect the running pane
tmux capture-pane -pt pylander-web

# Restart the server inside the existing session
tmux send-keys -t pylander-web C-c
tmux send-keys -t pylander-web 'uv run pygbag --port 8000 --template web/default.tmpl --icon web/favicon.png . > /tmp/pygbag-serve.log 2>&1' Enter
```

This is a dev convenience only. It is not the publishing model.

## Publishing

Publishing should treat `build/web/` as a static site artifact.

That means local `pygbag serve` is mainly for development, while deployment should
serve the generated files from a normal static host.

### Current target: GitHub Pages

Plan to publish from the `pylander` repo rather than routing the build through the
`blog` repo.

Recommended shape:

1. Build locally or in CI with pygbag.
2. Publish the contents of `build/web/` to GitHub Pages.
3. Keep the playable game hosted from a dedicated Pages path for this repo.

Good options:

- `gh-pages` branch containing the built static files, or
- GitHub Actions Pages deployment artifact sourced from `build/web/`

Prefer keeping the game deployment owned by the `pylander` repo itself. The blog
can link to it, but should not be the operational source of truth for the build.

### Self-hosted option

Self-hosting is also straightforward: copy `build/web/` to a static web root and
serve it with a standard web server or reverse-proxied container.

For the homelab, this likely means a small static container behind Traefik on
`docker.lan`.

## Dev server vs publishable artifact

Yes: now that the first pygbag build works, the next step is to think in terms of
**package/build/artifact publishing**, not only `pygbag`'s local dev server.

Use this mental split:

- **Development:** `uv run pygbag ...` for rebuild + localhost testing
- **Publishing:** serve `build/web/` as static files from GitHub Pages or another host

So the repo should gradually optimize for three things:

1. reproducible web build command
2. stable generated artifact in `build/web/`
3. straightforward static hosting target

Residual cleanup still worth doing before calling the publish path polished:

- remove raw `cookiecutter` template remnants from generated `index.html`
- decide whether CDN-hosted pygbag runtime assets are acceptable for production
- document the exact Pages deployment flow once selected

The build output goes to `build/web/` with:
- `index.html` - JavaScript loader
- `pylander.apk`, `pylander.tar.gz` - packaged application bundle
- `browserfs.min.js` and related loader assets as emitted by pygbag

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
