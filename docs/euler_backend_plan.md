# Euler physics backend plan

Pure-Python fallback physics backend for web (pygbag) and constrained platforms.
Pymunk stays the default on desktop and PortMaster. Euler is selected automatically
on `emscripten` or explicitly via `PYLANDER_PHYSICS=euler`.

## What the contact system actually reads

`ContactSystem` consumes a `ContactReport` from `PhysicsEngine.get_contact_report()`:

```python
@dataclass
class ContactReport:
    colliding: bool = False
    normal: tuple[float, float] | None = None   # collision surface normal
    rel_speed: float = 0.0                       # impact speed along normal
    point: tuple[float, float] | None = None     # world contact point (telemetry)
```

How each field is used by `ContactSystem`:

| Field | Used by | Decision |
|-------|---------|----------|
| `colliding` | Every path | Gates all landing/crash resolution |
| `normal` | `_is_landing_surface_contact` | `abs(normal_y) >= 0.65` → surface is flat enough to land |
| `rel_speed` | `_is_unsafe_colliding_impact` | `>= safe_landing_velocity` (10 m/s default) → crash |
| `point` | Not consumed by game logic | Telemetry only |

**The entire contract is: colliding (bool), normal (y-component for flatness check), rel_speed (magnitude along normal).**

## Collision detection approach

The lander is a triangle (3 vertices). Terrain is a chain of line segments within a
rolling window. Each frame:

1. **Broad phase**: Compare lander bottom (`pos.y - half_h`) against
   `terrain.height_at(pos.x)`. If not close, no collision.

2. **Narrow phase**: For each of the lander's 3 edges, test against the ~5-10
   terrain segments within the lander's x-footprint. This is line-vs-line
   intersection — trivial math.

3. **Contact data**:
   - `colliding = True` when any lander edge intersects a terrain segment
   - `normal` = perpendicular of the terrain segment that was hit
   - `rel_speed = abs(dot(velocity, normal))` — impact speed along collision normal
   - `point` = intersection point

4. **Penetration correction**: Push the body out of terrain along the collision
   normal so it doesn't tunnel further. With elasticity=0.0, this is just "stop
   penetrating."

5. **Separation detection**: If previously colliding and no intersection this
   frame, emit `colliding=False`.

At 60 Hz with max lander speed ~50 m/s, the body moves ~0.83 m/frame. The lander
is ~8 m tall. Tunneling is extremely unlikely at normal gameplay speeds.

## Body state and integration

Symplectic Euler (update velocity then position):

```
velocity += (force / mass + gravity) * dt
position += velocity * dt
```

Body state per actor:
- `position: (x, y)` — world coordinates, y-up
- `velocity: (vx, vy)`
- `angle: float` — radians, set directly (not via torque)
- `angular_velocity: float` — read back but not driven by physics

## Segment storage

Terrain segments are stored as `((x1, y1), (x2, y2))` tuples in a dict keyed by
handle ID — same pattern as `PymunkBackend`. No physics library objects needed.

## Raycast

Line-vs-line-segment intersection test across all terrain + landing site segments.
Return first hit (closest). Only used by bot sensor systems — not needed for
human-player portable build, but trivial to implement for completeness.

## Moment of inertia

Closed-form for a convex polygon:

```python
def moment_for_poly(mass, verts):
    # Second moment of area / area * mass
    # For a triangle this has an exact formula.
    # General polygon: shoelace-based formula.
```

Not actually needed for gameplay (angle is set directly, not driven by torque), but
the protocol requires it. Compute and store but don't use in integration.

## File layout

```
core/physics_euler.py    # ~250-300 lines
```

Implements `PhysicsBackend` protocol. No external dependencies — pure Python + `math`.

## Backend selection

```python
# core/physics_backend.py — default_backend()
if explicit == "euler":
    return EulerBackend()
if sys.platform == "emscripten":
    return EulerBackend()
# default
return PymunkBackend()
```

Pymunk remains default everywhere except emscripten. Euler is testable on desktop
via `PYLANDER_PHYSICS=euler`.

## Parity testing strategy

Run the same physics test suite against both backends:

```python
# tests/test_physics_parity.py
@pytest.fixture(params=["pymunk", "euler"])
def backend_engine(request):
    ...
```

Key parity checks:
1. **Gravity**: body falls at correct rate (position after N steps matches pymunk within tolerance)
2. **Thrust**: force application produces correct acceleration
3. **Collision detection**: body detects terrain contact at same position
4. **Collision normal**: surface normal matches (y-component >= 0.65 for flat terrain)
5. **Impact speed**: rel_speed matches within tolerance
6. **Penetration correction**: body doesn't fall through terrain
7. **Teleport/set_velocity**: state changes apply correctly

Tolerances: physics is inherently divergent between solvers. Expect position drift
< 0.5 m after 5 seconds, collision timing within 1 frame, impact speed within 5%.

## Implementation order

1. Create `core/physics_euler.py` with `EulerBackend` class
2. Wire `default_backend()` for `euler` and `emscripten`
3. Create `tests/test_physics_parity.py` comparing both backends
4. Run full test suite with `PYLANDER_PHYSICS=euler` to find gaps
5. Run a headless sim with both backends and compare outcomes

## Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Collision edge cases (vertex-vs-vertex, grazing) | Medium | Flat terrain is the primary surface; edge cases rare in practice |
| Position drift vs pymunk over long runs | Low | Euler won't match exactly; acceptable for web build |
| No continuous collision detection | Low | Speed cap or simple sweep test if tunneling observed |
| Angular velocity not physics-driven | Low | Angle is set directly in current game; no torque simulation needed |
