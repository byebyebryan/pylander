# Portable build research

Investigation into running pylander as-is on low-power devices (PortMaster / rg351v) and web (pygbag), without forking the codebase.

## Target devices

### rg351v (via PortMaster)

| Spec | Value |
|------|-------|
| CPU | Rockchip RK3326, quad-core Cortex-A35 @ 1.5 GHz |
| RAM | 1 GB DDR3L |
| Screen | 640×480, 4:3 IPS |
| OS | Linux (ArkOS / ROCKNIX) |
| Arch | `aarch64` (or `armhf` on older CFW) |
| Input | D-pad, face buttons, dual analog — mapped via gptokeyb to keyboard/mouse |

### Web (via pygbag)

| Spec | Value |
|------|-------|
| Runtime | CPython 3.11/3.12 compiled to WASM |
| Render | pygame-ce via SDL2 emscripten port |
| Input | Keyboard, mouse, touch |
| Limits | No native C extensions unless prebuilt for pygbag's WASM ABI; async game loop required |

---

## Remote desktop fallback (SSH X11)

Before committing to a web build, it is possible to run the desktop pygame build remotely over SSH X11 forwarding for occasional smoke tests.

### What worked

- Remote host can be headless (no active local Wayland session required)
- `sshd` must have:
  - `X11Forwarding yes`
  - `X11UseLocalhost yes`
- Local machine must have a valid Xauthority cookie for its Xwayland display
- On the remote side, force SDL to X11/software rendering

### Firewall / sshd notes

- LAN access debugging exposed a firewalld rule on `starship` that blocked custom ports even in the `home` zone. Do not assume `home` means "all ports open."
- `sshd` defaults on Arch had `X11Forwarding` commented out, which effectively disabled it until a drop-in was added.

### Known-good SSH X11 smoke test

```bash
ssh -Y starship.lan 'unset WAYLAND_DISPLAY; export SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy SDL_VIDEO_X11_FORCE_EGL=0 SDL_RENDER_DRIVER=software; /home/bryan/code/pylander/.venv/bin/python -c "import pygame, time; pygame.init(); print(\"driver=\", pygame.display.get_driver()); pygame.display.set_mode((640,480)); time.sleep(3)"'
```

Expected result:
- pygame window appears locally over SSH
- output includes `driver= x11`

### Pylander interactive smoke test over SSH X11

```bash
ssh -Y starship.lan 'cd /home/bryan/code/pylander && unset WAYLAND_DISPLAY; export SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy SDL_VIDEO_X11_FORCE_EGL=0 SDL_RENDER_DRIVER=software PYLANDER_PHYSICS=euler; uv run python main.py play'
```

### Caveat

This is useful for occasional visual verification, but it is too slow to be a comfortable daily workflow. Treat it as a fallback path, not the primary portable-dev loop.

---

## What to strip (human-player portable build)

The goal is a single repo with a build manifest that selects which files to package. No fork, no branch, no separate version.

### Remove entirely (bot / benchmark infrastructure)

| Module | Lines | Reason |
|--------|-------|--------|
| `bots/` (~15 files) | ~6,500 | Zero gameplay value for human player. Only consumer of `cvxpy`. |
| `app/` (~20 files) | ~5,000 | CLI parsing, batch runner, benchmark orchestration. Only consumer of `matplotlib`. |
| `utils/tracepack.py` | ~1,400 | Trace recording — bot eval infrastructure. |
| `utils/plot.py` | — | Matplotlib plotting — benchmark only. |
| `utils/botmetrics.py` | — | Bot metric aggregation. |
| `core/bot.py` | 386 | Bot abstract base, `BotAction`, `Sensors`, `BotEnvironment`. |
| `core/sensor.py` | 203 | Radar/proximity sensors — bot-only. |
| `core/systems/sensor_update.py` | 38 | Per-tick sensor computation. |
| `core/systems/scripted_control.py` | 74 | Scripted sequences — bot eval only. |
| `runtime/bot_loop.py` | 90 | Bot update loop. |
| `runtime/sensors.py` | 193 | Sensor building for bot consumption. |
| `runtime/terrain_intel.py` | 152 | Terrain analysis for bots. |
| `runtime/metrics.py` | 393 | Run metrics tracking — benchmark eval. |
| `runtime/result_pipeline.py` | 179 | Result processing — benchmark eval. |
| `runtime/plot_events.py` | 152 | Event plotting. |
| `tests/` | — | Not shipped in portable build. |
| `outputs/` | — | Local artifacts, never shipped. |
| `docs/` | — | Not needed on device. |

### Dependencies after stripping

| Library | Verdict | Notes |
|---------|---------|-------|
| `pymunk` | **Keep** | Core physics. CFFI backend — needs cross-compile for ARM, **not available for pygbag WASM**. |
| `pygame-ce` | **Keep** | Rendering. Has ARM builds (armv7, aarch64 CI). Available in pygbag. |
| `opensimplex` | **Keep** | Pure Python, tiny. Terrain generation. |
| `cvxpy` | **Remove** | Convex optimizer — bot-only, heavy C deps. |
| `matplotlib` | **Remove** | Plotting — benchmark-only, enormous. |
| `numpy` | **Remove** | Only used by `bot_framework/bots/pdg_optimizer.py`. |

Final portable deps: **pymunk + pygame-ce + opensimplex** (three packages on PortMaster), **pygame-ce + opensimplex** plus a physics fallback on pygbag.

### Simplify (not remove)

| Area | Change |
|------|--------|
| Multi-rate loop | Drop 120 Hz physics + 60 Hz bot. Single 60 Hz physics+render loop (or 60 Hz physics / 30 Hz render if CPU is tight). |
| ECS | Keep as-is. ~350 lines of thin Python. Not a performance concern at single-actor scale. |
| Levels | Keep infrastructure but trim to 1–2 level types for initial port. Don't ship the full catalog. |
| Sensor overlays | Remove — bot UI only. |

---

## Physics backend analysis

Pymunk is not available on pygbag (Pyodide WASM wheels are incompatible with pygbag's CPython WASM runtime). This means we need an alternative physics backend for the web target — and if we're writing one anyway, it's worth asking whether a custom engine could also replace pymunk on PortMaster (eliminating the CFFI cross-compile problem entirely).

### What pymunk actually does for pylander

Full audit of `core/physics.py` (530 lines) and all consumers. The API surface is surprisingly small:

**Objects created:**
- `pm.Space` — 1 instance, gravity set once
- `pm.Body` — 1 per actor (dynamic, with mass + moment of inertia)
- `pm.Poly` — 1–3 per actor (triangle or multi-polygon lander shape)
- `pm.Segment` — many, attached to `static_body` (terrain line segments + landing site pads)

**Per-frame operations:**
1. Apply thrust force at body center: `body.apply_force_at_world_point(force, body.position)`
2. Override body angle: `body.angle = θ`
3. Step: `space.step(dt)`
4. Read back: `body.position`, `body.angle`, `body.velocity`, `body.angular_velocity`

**Collision detection (the hard part):**
- Callbacks: `begin`, `post_solve`, `separate` on collision type pair (lander vs terrain)
- From `post_solve`: reads `arbiter.normal` (collision normal vector), `contact_point_set.points[0].point_a` (world contact point)
- Computes `rel_speed = abs(dot(body.velocity, normal))` — impact speed along collision normal
- From `begin`/`separate`: tracks `colliding: bool`

**Raycast:**
- `space.segment_query(p1, p2, radius, ShapeFilter())` — used for proximity sensor
- Returns first hit: `info.point` (world position), `info.alpha` (normalized distance)
- **Only used by bot sensor systems** — not needed for human-player portable build.

**Other operations:**
- `body.mass = ...` — fuel burn mass updates
- `body.velocity = (...)`, `body.angular_velocity = ...` — teleport/reset
- `body.position = (...)` — teleport
- `pm.moment_for_poly(mass, verts)` — compute rotational inertia at creation time

### What the contact system actually needs

`ContactSystem` (`core/systems/contact.py`, 260 lines) receives a `ContactReport`:

```python
@dataclass
class ContactReport:
    colliding: bool = False
    normal: tuple[float, float] | None = None   # collision normal (x, y)
    rel_speed: float = 0.0                       # impact speed along normal
    point: tuple[float, float] | None = None     # world contact point
```

How each field is used:
- `colliding` — gates all crash/landing resolution
- `normal` — checked: `abs(normal_y) >= 0.65` to determine if surface is flat enough for landing
- `rel_speed` — compared against `safe_landing_velocity` (10 m/s) to determine safe vs crash
- `point` — present but not actually consumed by game logic (telemetry only)

**This is the entire contract.** The contact system does not use friction, elasticity, impulse, multiple contact points, or any other advanced collision data.

### Option A: Custom Euler physics (no external dependency)

#### What it needs to implement

| Feature | Difficulty | Notes |
|---------|-----------|-------|
| Rigid body state (pos, vel, angle, angular_vel) | Trivial | Just floats + Euler integration |
| Thrust force → acceleration (F=ma) | Trivial | Already in pylander-lite |
| Gravity | Trivial | Add to vy each step |
| Moment of inertia for polygon | Easy | Closed-form formula for triangle moment of inertia |
| Torque from thrust offset | Easy | If thrust is applied at center, no torque needed |
| **Collision: polygon vs line segments** | **Moderate** | SAT or GJK for triangle-vs-segment |
| **Collision normal computation** | **Moderate** | Need the surface normal at contact point |
| **Collision penetration resolution** | **Moderate** | Push body out of terrain to prevent tunneling |
| Raycast (segment vs terrain) | Easy | Line-line intersection — but **not needed for portable** |
| Rolling terrain window | Trivial | Just track which height samples are active |

#### The collision problem in detail

The lander is a triangle (3 vertices). Terrain is a chain of line segments. Each frame:

1. **Broad phase**: Check if lander is near terrain (compare `lander.y + half_h` against `terrain.height_at(lander.x)`). Very cheap.
2. **Narrow phase**: If close, test each lander edge (3 edges) against nearby terrain segments (~5–10 segments within the lander's footprint). This is line-vs-line intersection — trivial math.
3. **Contact data**: The terrain segment's normal is just the perpendicular to the segment direction. The contact point is the intersection point. `rel_speed = abs(dot(velocity, normal))`.

For a single triangle vs terrain, this is **~30 intersection tests per frame at most** — negligible even on a 1.5 GHz A35.

#### What about penetration / tunneling?

At 60 Hz with dt=1/60s and max lander speed ~50 m/s, the lander moves ~0.83 m per frame. The lander is 8 m tall. Tunneling through terrain is extremely unlikely at normal gameplay speeds. A simple post-step correction (clamp body above terrain if it penetrates) is sufficient.

The current pymunk build already uses elasticity=0.0 (no bounce), so the collision response is essentially: "stop penetrating." A custom engine can do this trivially.

#### Estimated effort: ~200–300 lines

The pylander-lite `Lander` class is 70 lines and handles Euler integration + basic collision. Adding proper polygon collision detection and the `ContactReport` contract would roughly triple that. The old adapter/protocol layer added boilerplate but no algorithmic complexity.

**Confidence: high.** This is a solved problem. The only physics in this game is: one rigid body falling under gravity with thrust, colliding with a static heightmap.

#### Benefits over pymunk
- **Zero C dependencies** — pure Python, works everywhere (pygbag, PortMaster, desktop)
- **No cross-compile** — eliminates the hardest PortMaster packaging problem
- **Smaller bundle** — no Chipmunk/CFFI .so files
- **No version skew** — no pymunk/Chipmunk API changes to track
- **Debuggable** — all physics code is Python you can step through
- **Full control** — can tune collision margins, CCD, etc. for game feel

#### Risks
- **Behavioral drift from desktop pymunk build** — if we keep pymunk for desktop (with bots), the physics feel may differ slightly between desktop and portable. Mitigation: identical constants (gravity, friction), same ECS systems consuming physics output. The collision detection approach differs but the game logic above it is identical.
- **Edge cases in collision** — pymunk's solver handles corner cases (multiple simultaneous contacts, stacking, etc.) that a custom engine might get wrong. For a single lander on terrain, these scenarios are extremely rare.
- **No continuous collision detection (CCD)** — at very high speeds the lander could tunnel. Mitigation: clamp maximum speed or add a simple sweep test.

### Option B: Box2D (available on pygbag)

Box2D (`Box2D-2.3.10-cp311-cp311-wasm32_mvp_emscripten.whl`) is prebuilt in pygbag's archives. It's a full rigid body physics engine — more than capable of handling pylander's needs.

#### What it would require

| Task | Effort | Notes |
|------|--------|-------|
| Learn Box2D Python API | Low | Well-documented, similar concepts to pymunk |
| Implement `PhysicsEngine` with Box2D backend | ~300–400 lines | Map pymunk concepts → Box2D equivalents |
| Collision callbacks | Moderate | Box2D uses a different contact listener pattern |
| Raycast | Low | Box2D has `RayCast` on world |
| Testing | Moderate | Need to verify identical game behavior |

#### Box2D ↔ pymunk mapping

| pymunk | Box2D (Python) |
|--------|----------------|
| `pm.Space` | `b2World` |
| `pm.Body(mass, moment)` | `b2BodyDef` + `b2Body.CreateFixture` |
| `pm.Poly(body, verts)` | `b2PolygonShape(vertices)` |
| `pm.Segment(static_body, p1, p2, r)` | `b2EdgeShape(p1, p2)` on static body |
| `space.gravity = (gx, gy)` | `b2World(gravity=(gx, gy))` |
| `body.apply_force_at_world_point(f, p)` | `body.ApplyForce(f, p, wake=True)` |
| `space.step(dt)` | `world.Step(dt, vel_iters, pos_iters)` |
| Collision callbacks | `b2ContactListener` subclass |
| `space.segment_query(...)` | `world.RayCast(callback, p1, p2)` |

#### Estimated effort: ~300–400 lines

Similar to custom Euler, but with more API boilerplate. The physics is "free" (Box2D handles collision detection/response) but the adapter code is denser due to Box2D's C++-style API.

#### Benefits
- **Battle-tested collision** — Box2D is production-proven in thousands of games
- **Full physics** — friction, restitution, joints, CCD, all available if needed
- **Prebuilt on pygbag** — zero effort for WASM build
- **Available on ARM** — Box2D Python wheels exist for aarch64, could replace pymunk on PortMaster too

#### Risks
- **New dependency** — adds Box2D as a dependency alongside or replacing pymunk. Three physics backends (pymunk, Box2D, custom) would be worse than one.
- **API impedance mismatch** — Box2D's Python binding has quirks (mutable vectors, fixture-based shape creation, different coordinate conventions)
- **Version risk** — the pygbag Box2D wheel is version 2.3.10 which is the "Box2D flip" (old API), not the newer Box2D v3. API surface is different.
- **Doesn't solve the "two physics backends" problem** — if we keep pymunk for desktop, we still have two physics implementations to keep in sync. If we replace pymunk with Box2D everywhere, that's a bigger migration affecting bot behavior.

### Recommendation: Backend-agnostic physics layer

Instead of replacing pymunk, redesign the physics layer to accept multiple backends. **Pymunk stays as the desktop backend (bot compat). Box2D becomes the portable backend (pygbag + PortMaster).** If Box2D proves itself on portable, it can become the default everywhere later.

Rationale:

1. **Pymunk works on desktop.** Bots are trained against it. No reason to disrupt that until there's clear benefit.
2. **Box2D scales with gameplay.** Multiple bodies, joints, constraints, CCD — all available if the game design calls for it. No ceiling.
3. **One architecture, two implementations.** The game logic (ECS systems, contact resolution, propulsion) stays identical. Only the low-level physics primitives differ.
4. **Incremental migration path.** Start with Box2D for portable only. If it works well, evaluate replacing pymunk on desktop later — without another architecture change.

---

## Physics backend architecture

### Historical state (before refactor)

```
core/physics.py          530 lines — PhysicsEngine class, pymunk throughout
core/physics_adapter.py   167 lines — PhysicsAdapter wrapped PhysicsEngine
utils/protocols.py        59 lines — former EngineProtocol typing helper
levels/common_world.py           — constructed PhysicsEngine directly
```

`PhysicsEngine` is a monolith: it mixes pymunk-specific code (Space, Body, collision callbacks) with game-level orchestration (terrain window management, control tracking, UID resolution, force queuing).

### Proposed state (layered)

Split `PhysicsEngine` into two layers:

1. **`PhysicsBackend` protocol** — low-level primitives that a physics library must provide. Pure interface, no game logic.
2. **`PhysicsEngine`** — game-level orchestration (unchanged public API). Delegates to a backend. Contains the terrain window, control tracking, UID resolution, etc.

```
core/
├── physics.py                   # PhysicsEngine (backend-agnostic orchestration)
├── physics_backend.py           # PhysicsBackend protocol definition
├── physics_pymunk.py            # PymunkBackend implementation
├── physics_box2d.py             # Box2DBackend implementation (new)
```

### PhysicsBackend protocol

The backend is a thin wrapper over the physics library. It owns the simulation space, bodies, and shapes. It reports collisions as **data** (not callbacks) — the engine queries after each step.

```python
# core/physics_backend.py

from typing import Protocol
from core.components import ContactReport


@dataclass
class BodyState:
    """Immutable snapshot of a body's kinematic state."""
    position: tuple[float, float]
    angle: float
    velocity: tuple[float, float]
    angular_velocity: float


class PhysicsBackend(Protocol):
    """Low-level physics primitives.

    The backend owns the simulation space, bodies, and shapes.
    The engine drives it via this interface.
    """

    # --- Lifecycle ---

    def configure(self, gravity: tuple[float, float]) -> None:
        """Set gravity. Called once at creation."""
        ...

    # --- Actor management ---

    def create_body(
        self,
        uid: str,
        mass: float,
        polygons: list[list[tuple[float, float]]],
        position: tuple[float, float],
        angle: float,
        friction: float,
        elasticity: float,
    ) -> None:
        """Create a dynamic body with one or more convex polygon shapes."""
        ...

    def remove_body(self, uid: str) -> None:
        """Remove a body and all its shapes."""
        ...

    def set_mass(self, uid: str, mass: float) -> None:
        """Update body mass."""
        ...

    # --- Terrain ---

    def add_terrain_segments(
        self,
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
        friction: float,
        elasticity: float,
    ) -> list[int]:
        """Add static terrain line segments. Returns handle IDs."""
        ...

    def remove_terrain_segments(self, handles: list[int]) -> None:
        """Remove terrain segments by handle."""
        ...

    # --- Per-step input ---

    def set_force(self, uid: str, force: tuple[float, float]) -> None:
        """Queue a force to apply at body center next step."""
        ...

    def set_angle_override(self, uid: str, angle: float) -> None:
        """Override body angle (directly set, not via torque)."""
        ...

    def set_velocity(self, uid: str, vel: tuple[float, float], angular: float) -> None:
        """Set body velocity directly."""
        ...

    def teleport(self, uid: str, pos: tuple[float, float], angle: float | None) -> None:
        """Move body instantly."""
        ...

    # --- Simulation ---

    def step(self, dt: float) -> dict[str, ContactReport]:
        """Advance simulation. Returns contact reports keyed by actor UID."""
        ...

    def get_state(self, uid: str) -> BodyState:
        """Read current body state."""
        ...

    # --- Queries ---

    def raycast(
        self,
        origin: tuple[float, float],
        endpoint: tuple[float, float],
        ignore_uid: str | None,
    ) -> dict | None:
        """Segment query. Returns {point, distance} or None."""
        ...

    @staticmethod
    def moment_for_poly(mass: float, verts: list[tuple[float, float]]) -> float:
        """Compute rotational inertia for a polygon."""
        ...
```

### What moves where

The current `PhysicsEngine` (530 lines) splits along a clear seam:

| Responsibility | Lines | Where it goes |
|---|---|---|
| Space/body/shape creation (pymunk API) | ~120 | `PymunkBackend` |
| Collision callbacks → ContactReport | ~50 | `PymunkBackend` |
| Raycast (pymunk segment_query) | ~25 | `PymunkBackend` |
| moment_for_poly wrapper | ~5 | `PymunkBackend` |
| step() body iteration (apply forces, set angles) | ~20 | `PymunkBackend.step()` |
| **Terrain window management** | ~40 | Stays in `PhysicsEngine` |
| **Control/force/override queuing** | ~30 | Stays in `PhysicsEngine` |
| **UID resolution, actor tracking** | ~40 | Stays in `PhysicsEngine` |
| **Public API** (get_pose, get_velocity, etc.) | ~80 | Stays in `PhysicsEngine` (delegates to backend) |
| **Landing site collider management** | ~30 | Stays in `PhysicsEngine` (calls backend.add_terrain_segments) |

`PhysicsEngine` stays at roughly ~250 lines. Each backend implementation is ~150–200 lines.

### How PhysicsEngine uses the backend

```python
# core/physics.py (simplified)

class PhysicsEngine:
    def __init__(self, height_sampler, gravity, segment_step=10.0, half_width=12000.0,
                 *, backend: PhysicsBackend | None = None):
        self._backend = backend or default_backend()
        self._backend.configure(gravity)
        self.height_sampler = height_sampler
        self._terrain_handles: list[int] = []
        # ... same actor tracking dicts as before ...

    def step(self, dt: float) -> None:
        # 1. Maintain terrain window (generic — just height samples)
        self._ensure_window_centered(cx)

        # 2. Feed queued forces/angles to backend
        for uid in self._bodies:
            if uid in self._pending_forces:
                self._backend.set_force(uid, self._pending_forces.pop(uid))
            elif uid in self._controls:
                thrust, angle = self._controls[uid]
                self._backend.set_angle_override(uid, angle)
                if thrust > 0:
                    force = (sin(angle) * thrust, cos(angle) * thrust)
                    self._backend.set_force(uid, force)

        # 3. Step the backend
        contacts = self._backend.step(dt)

        # 4. Read back state
        for uid in self._bodies:
            state = self._backend.get_state(uid)
            # update internal tracking...

        # 5. Store contact reports
        self._contacts = contacts
```

### Backend selection

A factory function picks the default backend. Configurable via env var for explicit override:

```python
# core/physics_backend.py

import os
import sys


def default_backend() -> PhysicsBackend:
    """Select backend based on environment."""
    explicit = os.environ.get("PYLANDER_PHYSICS")
    if explicit == "pymunk":
        from core.physics_pymunk import PymunkBackend
        return PymunkBackend()
    if explicit == "box2d":
        from core.physics_box2d import Box2DBackend
        return Box2DBackend()
    # Auto-detect
    if sys.platform == "emscripten":
        from core.physics_box2d import Box2DBackend
        return Box2DBackend()
    # Desktop default
    from core.physics_pymunk import PymunkBackend
    return PymunkBackend()
```

No env var needed in normal use — desktop gets pymunk, pygbag gets Box2D. The env var is for testing (run Box2D on desktop to verify parity).

### Construction site: where PhysicsEngine is created

Currently two call sites in `levels/common_world.py`:

```python
# Line 89 and Line 538 — both do:
engine = PhysicsEngine(
    height_sampler=terrain,
    gravity=(0.0, float(GRAVITY)),
    segment_step=10.0,
    half_width=12000.0,
)
```

These don't change. `PhysicsEngine.__init__` calls `default_backend()` internally. The level code doesn't know or care which backend is active.

For explicit control (e.g., benchmarks comparing backends), pass `backend=`:
```python
engine = PhysicsEngine(..., backend=Box2DBackend())
```

### What the Box2D backend looks like

```python
# core/physics_box2d.py

import Box2D
from core.components import ContactReport
from core.physics_backend import PhysicsBackend, BodyState


class Box2DBackend:
    def __init__(self):
        self._world: Box2D.b2World | None = None
        self._bodies: dict[str, Box2D.b2Body] = {}

    def configure(self, gravity: tuple[float, float]) -> None:
        self._world = Box2D.b2World(gravity=gravity)

    def create_body(self, uid, mass, polygons, position, angle, friction, elasticity):
        bd = Box2D.b2BodyDef()
        bd.type = Box2D.b2_dynamicBody
        bd.position = position
        bd.angle = angle
        body = self._world.CreateBody(bd)
        for poly in polygons:
            fd = Box2D.b2FixtureDef()
            fd.shape = Box2D.b2PolygonShape(vertices=poly)
            fd.density = mass / total_area  # Box2D uses density, not mass
            fd.friction = friction
            fd.restitution = elasticity
            body.CreateFixture(fd)
        self._bodies[uid] = body

    def step(self, dt):
        self._world.Step(dt, velocityIterations=6, positionIterations=2)
        return self._collect_contacts()

    def get_state(self, uid):
        body = self._bodies[uid]
        return BodyState(
            position=(body.position.x, body.position.y),
            angle=body.angle,
            velocity=(body.linearVelocity.x, body.linearVelocity.y),
            angular_velocity=body.angularVelocity,
        )
    # ... etc
```

### Migration strategy

1. **Extract protocol** — Define `PhysicsBackend` protocol in `core/physics_backend.py`.
2. **Extract pymunk backend** — Move all pymunk calls from `core/physics.py` into `core/physics_pymunk.py`. `PymunkBackend` wraps pymunk and implements the protocol.
3. **Refactor PhysicsEngine** — Replace direct pymunk calls with backend delegation. Keep all game logic (terrain window, control queuing, UID resolution).
4. **Verify parity** — Run existing physics tests against refactored `PhysicsEngine` + `PymunkBackend`. Behavior must be identical.
5. **Add Box2D backend** — Implement `Box2DBackend` in `core/physics_box2d.py`.
6. **Test Box2D path** — Run `PYLANDER_PHYSICS=box2d uv run pytest tests/test_physics.py`.
7. **Build portable** — Portable builds include `physics_box2d.py` but exclude `physics_pymunk.py` and the `pymunk` dependency.

Steps 1–4 are a zero-behavior-change refactor. The existing test suite validates it. Steps 5–6 add the new backend. Step 7 is the build script (already planned).

### Dependency matrix after migration

| Package | Desktop | Portable (PortMaster) | Portable (pygbag) |
|---------|---------|----------------------|-------------------|
| `pymunk` | ✅ (PymunkBackend) | ❌ excluded | ❌ not available |
| `Box2D` | ❌ optional | ✅ (Box2DBackend) | ✅ (prebuilt WASM wheel) |
| `pygame-ce` | ✅ | ✅ | ✅ |
| `opensimplex` | ✅ | ✅ | ✅ |

---

## PortMaster packaging model

PortMaster doesn't have a traditional build system. Each "port" is:

1. **A directory of files** → zipped for distribution.
2. **A launch script** (`.sh`) — sets up env vars, mounts runtimes, launches the game.
3. **Optionally depends on a shared runtime** (squashfs image mounted on demand from `$controlfolder/libs/`).

### Port directory structure

```
pylander/
├── port.json              # Metadata (title, genres, arch, runtime deps)
├── Pylander.sh            # Launch script
├── README.md
├── screenshot.png         # 640×480 4:3 gameplay screenshot
├── gameinfo.xml           # EmulationStation metadata
├── cover.jpg              # Optional
└── pylander/              # Game files
    ├── licenses/
    ├── main_portable.py   # Thin entrypoint
    ├── core/              # (subset)
    ├── runtime/           # (subset)
    ├── levels/            # (subset)
    ├── ui/                # (full)
    ├── landers/           # (full)
    └── configs/
```

Note: with custom physics, there are no `libs.aarch64/` directories needed. Everything is pure Python.

### Available shared runtimes

PortMaster provides squashfs runtimes for Python, Godot, Mono, Java, Pyxel, etc. The Python 3.11 runtime (`python_3.11.squashfs`) is `aarch64`-only. It provides the interpreter; Python packages with C extensions must be bundled in the port's `libs.${DEVICE_ARCH}/` directory.

With custom physics + pygame-ce (available in the Python runtime or bundled as a pure wheel), the only C dependency is pygame-ce itself. This is much simpler than the pymunk scenario.

### Launch script pattern

```bash
#!/bin/bash
# ... detect controlfolder, source control.txt, get_controls ...
GAMEDIR="/$directory/ports/pylander/pylander"
cd "$GAMEDIR"

# Mount Python runtime
runtime="python_3.11"
# (download + mount squashfs — standard PortMaster pattern)

# Controller mapping
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
$GPTOKEYB "python3.11" -c "./pylander.gptk" &

# Launch
pm_platform_helper "python3.11"
"$python_bin" "$GAMEDIR/main_portable.py"

pm_finish
```

### Key env vars (provided by control.txt)

| Variable | Description |
|----------|-------------|
| `$DEVICE_ARCH` | `aarch64`, `armhf`, or `x64` |
| `$DEVICE_RAM` | RAM in GB (for conditional behavior) |
| `$CFW_NAME` | Firmware identifier (ArkOS, ROCKNIX, etc.) |
| `$directory` | `roms` or `roms2` |
| `$GPTOKEYB` | Path to gamepad→keyboard mapper |
| `$sdl_controllerconfig` | SDL controller mapping string |

---

## Pygbag packaging model

Pygbag bundles **whatever's in the directory you point it at**. Filtering via:

1. Built-in ignores (`.git`, `venv`, `__pycache__`, etc.)
2. `pygbag.ini` `ignoreDirs` / `ignoreFiles`
3. Auto dependency resolution from PEP 723 inline metadata

### Key constraints

- **Async game loop required**: `await asyncio.sleep(0)` must be called each frame to yield control to the browser event loop.
- **Custom physics = zero issues**: Pure Python, no C extensions needed.
- **pygame-ce available**: Prebuilt in pygbag's WASM runtime.
- **opensimplex**: Pure Python, bundles trivially.
- **Resolution**: Browser-resizable.

### Build approach

Point pygbag at a staging directory created by the same build script that creates the PortMaster package:

```bash
python scripts/build_portable.py --target pygbag --output /tmp/pylander-web/
pygbag /tmp/pylander-web/
```

---

## Unified build strategy

One repo, one build script, two output targets.

### Proposed repo layout

```
pylander/
├── main.py                   # Desktop entry (full game, bots, benchmarks)
├── main_portable.py          # Portable entry (human-only, no bots)
├── core/
│   ├── physics.py            # PhysicsEngine (backend-agnostic orchestration)
│   ├── physics_backend.py    # PhysicsBackend protocol + factory
│   ├── physics_pymunk.py     # PymunkBackend (desktop)
│   ├── physics_box2d.py      # Box2DBackend (portable)
│   └── ...
├── runtime/
├── bots/                     # Desktop-only — excluded from portable builds
├── app/                      # Desktop-only — excluded from portable builds
├── ui/
├── levels/
├── landers/
├── scripts/
│   └── build_portable.py     # Build script — creates staging dir for each target
├── portable/                 # PortMaster packaging metadata
│   ├── port.json
│   ├── Pylander.sh
│   ├── gameinfo.xml
│   ├── pylander.gptk         # gptokeyb controller mapping
│   └── screenshot.png
└── pygbag.ini                # Pygbag filtering config (alternative to staging dir)
```

### Build script role

`scripts/build_portable.py` is the single source of truth for what the portable build contains:

- Defines the file inclusion/exclusion manifest.
- Copies approved files to a staging directory.
- For PortMaster: wraps staging dir into PortMaster zip format with launch script.
- For pygbag: outputs staging dir ready for `pygbag` command.

### Physics backend selection

Backend is selected automatically at construction time:

```python
# core/physics_backend.py — default_backend()
# Desktop (no env var) → PymunkBackend
# sys.platform == "emscripten" → Box2DBackend
# PYLANDER_PHYSICS=pymunk → PymunkBackend (explicit)
# PYLANDER_PHYSICS=box2d → Box2DBackend (explicit, for desktop testing)
```

Portable builds don't include `physics_pymunk.py` or the `pymunk` package. Desktop builds don't require Box2D (optional for cross-testing).

No code forks. Same game logic, same ECS systems, same rendering — just a different physics implementation injected at construction.

---

## Differences between targets

| Concern | PortMaster (ARM) | pygbag (WASM) |
|---------|-------------------|---------------|
| Physics | Box2D (prebuilt ARM wheel or bundled .so) | Box2D (prebuilt WASM wheel) |
| Entry point | `.sh` launch script → `main_portable.py` | `main_portable.py` with async loop |
| Resolution | Fixed 640×480 | Browser-resizable |
| Input | gptokeyb maps gamepad → keyboard events | Keyboard / touch |
| Python deps | Box2D + pygame-ce + opensimplex | Box2D + pygame-ce + opensimplex |
| Python runtime | Mounted from squashfs | Embedded in pygbag bundle |

---

## Open questions

1. **Python version**: PortMaster's Python 3.11 runtime vs pylander's 3.13+ requirement. Need to check if any 3.13-only syntax/features are used in the portable subset, or if we need a 3.13+ runtime squashfs.
2. **Box2D Python version**: The pygbag Box2D wheel targets CPython 3.11 WASM. Need to verify Box2D Python bindings work on 3.11 for PortMaster (which uses the 3.11 runtime). Desktop stays on 3.13+ with pymunk.
3. **Desktop pymunk → Box2D migration**: Start with pymunk for desktop, Box2D for portable. Evaluate migrating desktop to Box2D later based on portable experience. Bot eval benchmarks would need re-baselining if we switch.
4. **Performance on device**: Box2D C backend on ARM should be fast. Single lander + terrain at 60 Hz is trivial workload. Needs real-device testing.
5. **pylander-lite deprecation**: Once portable builds work from the main repo, decide whether to archive pylander-lite or keep it as a minimal reference.
