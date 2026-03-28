# Terrain Avoidance Design

Planning note for terrain-aware transfer scenarios, bot APIs, and trace/plot requirements.

## Problem statement

Current transfer benchmarks intentionally ignore obstacle handling:

- `boost:*` only varies route family, route tier, and cargo weight.
- The base terrain in `boost` is either flat or a single uniform slope.
- Runtime bot sensors expose only local terrain state under the ship plus a short-range proximity contact.

That was the right simplification for the current boost and terminal rebuilds, but it is now the main gap:

- `boost` needs enough terrain information to plan a route that clears obstacles.
- `boost` and `terminal` both need a reactive avoidance layer during execution.
- Terrain scenarios need to explain failures, not just report `crashed`.

This doc proposes the first terrain-aware API and scenario model without breaking the bot/engine boundary.

## Goals

- Expose the full terrain to bots through a read-only query interface.
- Keep per-frame sensor snapshots lightweight on the hot path.
- Split terrain handling into:
  - long-horizon planning during `boost`
  - short-horizon reactive avoidance during `boost` and `terminal`
- Add a curated terrain scenario catalog that covers both planning and reactive behaviors.
- Make trace/plot outputs visually explain why a terrain-aware run passed or failed.

## Non-goals

- Do not fold terrain obstacles into the existing public `boost:*` selector root.
- Do not expose mutable engine internals or physics colliders directly to bots.
- Do not start with randomized obstacle fuzzing or a giant parameter cross product.

## Current state

Relevant code today:

- `boost` terrain/catalog: [`../levels/boost.py`](../levels/boost.py), [`../levels/boost_catalog.py`](../levels/boost_catalog.py)
- per-frame bot sensor build: [`../runtime/sensors.py`](../runtime/sensors.py)
- sensor update system: [`../core/systems/sensor_update.py`](../core/systems/sensor_update.py)
- bot API: [`../core/bot.py`](../core/bot.py)
- terrain helpers: [`../core/terrain.py`](../core/terrain.py), [`../core/sensor.py`](../core/sensor.py)
- trace/plot overlays: [`../utils/plot.py`](../utils/plot.py), [`../utils/traceviewer.py`](../utils/traceviewer.py)

Observed constraints:

- `boost` terrain is currently a simple height function with either `flat` or uniform `slope`.
- `Sensors` currently exposes:
  - centerline `terrain_y`
  - centerline `terrain_slope`
  - `altitude`
  - `proximity`
  - radar contacts for landing sites
- The trace viewer already renders:
  - terrain
  - flown trajectory
  - target pad
  - ballistic projection
  - a reference curve

The missing piece is not visualization infrastructure; it is the terrain-aware data and planning model behind those visuals.

## Bot terrain API

### Design direction

Expose terrain once at setup time through a read-only query object.

Do not pass the full terrain object inside every `Sensors` snapshot. The terrain is static for a run, so re-passing it every frame only adds hot-path churn and muddies the meaning of `Sensors`, which is currently "live local state."

The current `VehicleInfo` object should stay vehicle-only. Terrain belongs in a separate environment/setup payload.

### Proposed setup-time types

```python
@dataclass(frozen=True)
class BotTarget:
    uid: str | None
    x: float
    y: float
    size: float | None = None
    label: str | None = None


@dataclass(frozen=True)
class BotEnvironment:
    terrain: TerrainQuery
    gravity_mag: float
    target: BotTarget | None = None
    level_name: str | None = None
    scenario_name: str | None = None


class TerrainQuery(Protocol):
    def sample_height(self, x: float, lod: int = 0) -> float: ...
    def sample_slope(self, x: float, lod: int = 0) -> float: ...
    def profile(
        self,
        x0: float,
        x1: float,
        *,
        step: float,
        lod: int = 0,
    ) -> list[tuple[float, float]]: ...
    def resolution(self, lod: int = 0) -> float: ...
```

Notes:

- `TerrainQuery` should wrap the existing terrain sampler, not expose the raw engine object.
- The bot gets the same read-only query object for the entire run.
- `BotTarget` should mirror the runtime target corridor the bot is actually meant to fly toward.
- `profile()` is important for setup and replan windows. Terrain-aware planning needs more than point samples.
- In v1, `profile()` is explicitly not a per-tick reactive primitive.
- Keep v1 small. Shared higher-level helpers can live in a bot utility module rather than the protocol itself.

### Why this shape

- `sample_height()` and `sample_slope()` match the existing local fields already built in `runtime/sensors.py`.
- `profile()` supports obstacle scans, crest detection, and terrain-relative route construction.
- `resolution()` keeps downstream sampling stable and aligned to the terrain grid instead of hardcoding arbitrary step sizes.
- `target` breaks the current implicit dependence on live radar contacts for basic route construction.

If repeated reactive terrain summaries become necessary later, add a dedicated cached helper for window summaries instead of widening the hot-path meaning of `profile()`.

### Target contract

Terrain-aware boost planning should not depend on "whatever radar can currently see."

The setup payload should carry the primary target corridor explicitly:

- target uid when available
- target center x/y
- target size or half-width
- optional label for plots/debugging

That target should match the same destination used by:

- eval target resolution
- transfer success/failure checks
- plot target overlays

Radar remains useful for live contact tracking and multi-site worlds, but the terrain-aware planner should not need radar just to know where it is trying to go.

### Runtime integration

- Add a setup-time `set_environment()` hook on `Bot`.
- Build the `BotEnvironment` once during runtime bootstrap, near where `VehicleInfo` is already injected.
- Keep `Sensors` as the per-frame local snapshot.
- Keep radar/proximity in `SensorUpdateSystem` because those are still useful for reactive logic and UI/debugging.

## Control split

### Terrain-aware boost planning

`boost` should own the long-horizon terrain problem.

Responsibilities:

- scan upcoming terrain along the transfer corridor
- choose a route reference that clears relevant obstacles
- hand off into a terminal-entry state that is still recoverable
- avoid solving early terrain by creating an impossible late terminal trap

Expected output:

- a terrain-aware reference curve or route envelope
- clearance targets or route-shaping points that the boost optimizer can track

Planning should be able to solve:

- broad obstacles that require lofting before they are imminent
- mesas that reactive pull-up alone cannot clear
- multi-obstacle routes where the first solution cannot consume all vertical margin

### Reactive avoidance

Reactive avoidance should exist in both `boost` and `terminal`.

Responsibilities:

- monitor short-horizon terrain threat during execution
- detect when the current path or the current reference is no longer safe
- bias control upward or delay descent when a collision is imminent
- override or veto a nominal cutoff/handoff that would immediately collide with terrain

Reactive avoidance should use shared threat metrics across both phases so logs and plots stay consistent.

Example threat signals:

- minimum predicted clearance over a short forward horizon
- predicted time to terrain intercept
- required additional loft above the current reference
- whether the projected passive arc intersects terrain before the target corridor

Control split summary:

- `boost` planning solves broad route shape.
- `boost` reactive handles execution drift and late surprises.
- `terminal` reactive handles local crest/valley response during descent.

### Arbitration model

Reactive terrain avoidance should not be a second independent controller that competes with the active stage controller.

Recommended ownership model:

1. The active stage controller (`boost`, `coast`, `terminal`, `touchdown`) computes the nominal action.
2. A shared terrain guard evaluates short-horizon terrain threat against the current state and the nominal action.
3. The terrain guard may:
   - leave the action unchanged
   - request a terrain-driven replan
   - veto an unsafe cutoff / descent / handoff decision
   - apply a bounded upward bias or minimum-clearance floor
4. The routed action sent to control systems is the post-guard action.

This keeps one clear action owner per frame while still allowing terrain safety to override unsafe nominal behavior.

Guardrails for v1:

- the terrain guard must not synthesize a fully independent lateral plan
- the terrain guard must not replace the active stage controller wholesale
- long-horizon route selection stays with boost planning, not the guard

Responsibilities by layer:

- stage controller:
  - owns nominal mission progress
  - owns long-horizon route tracking
- terrain guard:
  - owns short-horizon terrain safety
  - owns terrain event emission and terrain threat state
- boost planner:
  - owns terrain-aware reference generation on replan windows

The terrain guard should be phase-aware, but its threat metrics should be shared so the bot does not maintain one terrain-safety model for boost and a different one for terminal.

## Performance contract

Full terrain access is acceptable only with an explicit hot-path boundary.

Rules:

- `profile()` scans belong to:
  - setup
  - replan windows
  - terrain-triggered replans
- per-frame reactive avoidance should consume:
  - cached terrain summaries
  - short-horizon forward samples
  - previously built terrain-aware references
- do not build large Python terrain profiles every bot tick

Practical implication:

- boost planning can afford richer terrain scans because it already replans at a lower rate
- reactive avoidance should operate on a bounded lookahead and fixed sampling budget
- terrain compute should show up in the existing passive/update timing metrics so regressions are measurable

## Terrain scenario root

Keep the current `boost:*` root as the clear-terrain baseline.

Add a separate terrain-focused transfer root instead of changing the existing public selector shape.

Working name:

- `terrain`

Proposed selector shape:

- `terrain:<family>:<route_tier>:<obstacle_case>:<weight_tier>`

Examples:

- `terrain:flat:mid:boost_table:half`
- `terrain:climb:high:double_ridge:full`

Rationale:

- existing `boost:*` selectors are already stable and used broadly
- obstacle handling deserves its own benchmark policy and pack curation
- this keeps clear-terrain regressions and terrain-aware regressions separable

## Scenario catalog design

Start with an explicit scenario catalog, not a giant generated matrix.

Each scenario should carry intent metadata directly in the catalog:

```python
@dataclass(frozen=True)
class ObstacleSpec:
    kind: Literal["ridge", "shoulder", "mesa"]
    x_fraction: float
    width: float
    height: float
    shoulder_width: float = 0.0
    face_bias: Literal["symmetric", "source_steep", "target_steep"] = "symmetric"


@dataclass(frozen=True)
class TerrainTransferScenario:
    name: str
    family: str
    route_tier: str
    weight_tier: str
    obstacle_case: str
    avoidance_band: Literal["reactive", "planning", "hybrid"]
    route_dx: float | SampleRange
    route_dy: float
    obstacles: tuple[ObstacleSpec, ...]
    context: str
    test_intent: str
    plot_focus: str
```

This keeps "why does this scenario exist?" attached to the selector instead of buried in external notes.

### Terrain-generation constraints

Obstacle scenarios still have to fit the current terrain model: a deterministic heightfield `x -> y`.

That means the first terrain catalog should explicitly support:

- ridges
- shoulders / slope breaks
- mesas / plateaus
- multi-crest heightfield combinations
- asymmetric faces through shoulder width and face bias

It should not try to model:

- vertical walls
- overhangs
- caves
- arbitrary disconnected geometry

Those would require a different collision and sensing model than the current height-sampler-based world.

### Reactive-first v1 scenario design

The first shipping `terrain:*` level should be reactive-first.

That means the initial normal-pack scenarios should only ask the controller to solve terrain problems that are locally recoverable through bounded upward bias, delayed descent, or cutoff vetoes.

Rules for v1 normal scenarios:

- exactly one obstacle per scenario
- obstacle geometry must be narrow enough that a local recovery is plausible
- obstacle cases should preserve the underlying clear-terrain family semantics instead of forcing a completely new route class
- prefer late obstacles first, because terminal-side shoulders and tables isolate reactive descent behavior cleanly
- allow early obstacles only when a boost-side shoulder or short table can be handled without sustained route reshaping

Do not put these in the initial normal pack:

- broad mesas that require a sustained higher route
- double-ridge scenarios
- hard margin-limited `climb:high:full` planning cases

Those belong in observe-only coverage until boost planning exists.

### Feature families by route type

Different baseline families should prefer different obstacle primitives.

- `flat`
  - prefer short flat-top obstacles (`table`) and broad flat-top obstacles (`mesa`)
  - a table is effectively a short mesa bounded by two shoulders
  - in v1, table cases should stay short enough to remain reactive-only
  - broad flat-top cases that require route shaping should use `mesa`, not an oversized `table`
- `downhill`
  - prefer `shoulder` cases over standalone ridges
  - a shoulder is a local slope hold / flatten / break that intrudes into the expected descent corridor
- `climb`
  - prefer `shoulder` cases over standalone ridges
  - a shoulder is a local roll-up or slope extension that makes a previously safe-looking climb/descent commitment unsafe

This keeps the terrain shapes natural for the underlying route family instead of dropping the same obstacle silhouette onto every baseline.

### Baseline route coverage

Use a small representative baseline set:

- `flat:mid`
- `downhill:mid`
- `climb:mid`

Reactive-first normal packs should start there.

Keep these for planning-phase expansion:

- `flat:far`
- `climb:high`

Weight coverage:

- default to `half`
- use `full` only where thrust margin is part of the point, especially `climb:high`

### Obstacle axes

Treat these as design axes, not all as public selector layers:

- location:
  - `boost` at roughly 20-30% of route length
  - `mid` at roughly 45-55%
  - `terminal` at roughly 70-85%
  - `double` with one early and one late obstacle
- geometry:
  - `shoulder`
  - `table`
  - `ridge`
  - `mesa`
  - `double_ridge`
- orientation:
  - source-steep
  - target-steep
- difficulty:
  - `low`
  - `medium`
  - `tight`

Public selector guidance:

- encode obstacle cases as named curated designs, for example `boost_shoulder`, `terminal_shoulder`, `boost_table`, `terminal_table`, `mid_mesa`, `double_ridge`
- keep width/height/asymmetry inside the scenario definition unless they become stable user-facing concepts later

This avoids a brittle selector explosion while the controller is still evolving.

### Determinism requirements

Each named obstacle case should resolve to deterministic geometry for a given selector and seed:

- route geometry must still follow the selected baseline family/tier
- obstacle positions should be defined relative to route progress, then materialized into concrete world x coordinates
- obstacle dimensions must be part of the catalog, not inferred ad hoc inside level setup
- if any obstacle dimension is randomized later, it must follow the existing benchmark median/sample rules and be recorded in scenario params

## Reactive-First Starter Set

The first normal-pack terrain catalog should stay small and intentionally reactive.

| Selector | Avoidance band | Context / why | What to test | Plot focus |
| --- | --- | --- | --- | --- |
| `terrain:flat:mid:boost_table:half` | `reactive` | Short early flat-top obstacle on an otherwise flat route. | Boost-side reactive guarding should preserve climb margin and block an unsafe early cutoff without demanding a new global route. | Table edges, boost cutoff veto, actual path over the flat top. |
| `terrain:flat:mid:mid_table:half` | `reactive` | Centered short flat-top obstacle with both source- and target-side shoulders affecting the same run. | Reactive correction should clear both table edges in one transfer without requiring terrain-aware planning. | Both table edges, actual dwell over the flat top, local clearance margin at each edge. |
| `terrain:flat:mid:terminal_table:half` | `reactive` | Short late flat-top obstacle near the target on otherwise normal terrain. | Terminal reactive avoidance should delay descent or bias upward without requiring a global replan. | Table edges, terminal entry, reactive-avoid start/end markers, flown path vs late obstacle. |
| `terrain:downhill:mid:boost_shoulder:half` | `reactive` | Source-side shoulder where the launch platform or early downhill profile extends before dropping. | Boost-side reactive logic should avoid cutting low off the source shelf and preserve safe initial descent geometry. | Source shoulder edge, boost cutoff veto, actual path leaving the shelf. |
| `terrain:downhill:mid:terminal_shoulder:half` | `reactive` | Downhill route that flattens into a shoulder before a steeper final drop to target. | Reactive logic should avoid diving into the shoulder or committing too early into the final drop. | Downhill terrain line, shoulder edge, terminal entry, descent delay or pull-up. |
| `terrain:climb:mid:boost_shoulder:half` | `reactive` | Source-side shoulder where the route looks easy initially before the climb steepens. | Boost-side reactive logic should avoid an early cutoff on the apparent shelf and preserve enough margin for the later climb. | Source shoulder edge, boost cutoff veto, actual path into the steeper climb. |
| `terrain:climb:mid:terminal_shoulder:half` | `reactive` | Climb route that eases into a shoulder before the final approach geometry tightens again. | Reactive logic should protect the terminal approach without requiring terrain-aware boost routing. | Slope baseline, terminal shoulder edge, terminal entry, delayed descent or upward bias. |

## Planning-Phase Expansion Set

Once boost planning exists, expand the catalog with cases that are not fairly solvable by local reactive action alone.

| Selector | Avoidance band | Context / why | What to test | Plot focus |
| --- | --- | --- | --- | --- |
| `terrain:flat:far:mid_mesa:half` | `planning` | Broad obstacle that should not be solvable by last-second pull-up. | Boost planning should choose a sustained higher route, not a low fast transfer that reacts too late. | Mesa profile, terrain-aware reference over the mesa, actual path duration over the obstacle. |
| `terrain:downhill:mid:boost_shoulder:full` | `hybrid` | Source-side shoulder on a heavier downhill route where a local-only reaction may become marginal. | Planner should preserve enough early vertical margin while reactive logic protects the cutoff window. | Source shoulder edge, planned loft, cutoff state, post-shoulder descent. |
| `terrain:climb:mid:boost_shoulder:full` | `hybrid` | Terrainized version of the current source-side climb margin problem. | Planner should separate "leave the shelf safely" from "reach the higher target" instead of treating the whole route as one smooth climb. | Source shoulder edge, planned climb profile, margin after the shoulder. |
| `terrain:climb:high:boost_shoulder:full` | `planning` | Hard margin-limited uphill case close to the current clear-terrain failure mode, but with an explicit source-side shoulder. | Planner must respect terrain under low excess thrust and avoid an apparently safe early cutoff that becomes unrecoverable later. | Shoulder edge, boost cutoff state, projected intercept, margin remaining to target corridor. |
| `terrain:climb:high:double_ridge:full` | `planning` | Early and late obstacles on the hardest uphill route. | Prevent "solve the first ridge, die at the second" behavior; force planner to preserve downstream terminal recoverability. | Both ridge crests, terrain-aware reference, terminal entry, actual path against both obstacles. |

## Reactive vs planning scenario bands

The scenario set should explicitly separate capability bands:

- `reactive`
  - narrow local obstacles
  - primary question: can execution-time avoidance recover safely?
- `planning`
  - broad or multi-obstacle terrain
  - primary question: did boost choose a route that was safe before the emergency was imminent?
- `hybrid`
  - planning should create margin, reactive should protect against execution drift

This split matters because a planning-required scenario should not silently fail the same way as a reactive-only scenario. They test different controller responsibilities.

For rollout:

- initial `terrain:*` normal packs should contain only `reactive` scenarios
- `hybrid` and `planning` scenarios should start as `observe_only`
- promote `hybrid` to `normal` only after boost planning exists and the traces are interpretable

## Plot and trace requirements

Terrain scenarios should be trace-first, but v1 should ship a minimal terrain telemetry slice before the full generalized overlay model.

Required v1 spatial overlays:

- terrain
- flown path
- target pad
- ballistic-from-event overlay when relevant
- obstacle crest markers or annotated obstacle regions
- boost cutoff marker
- terminal entry marker
- reactive avoidance markers

Required v1 timeseries/telemetry overlays:

- minimum predicted clearance
- predicted time to terrain intercept
- active terrain mode (`nominal`, `terrain_plan`, `reactive_avoid`)
- thrust / angle
- optional terrain guard reason or cutoff-veto state

Planning-phase additions:

- terrain-aware reference curve
- terrain-agnostic vs terrain-aware reference comparison
- route-reference gap metrics for the terrain-aware planner

### Trace schema changes

The current single `reference_curve` payload is enough for the first reactive-only pass, but it will not be enough once boost planning lands.

So the generalized overlay schema should be treated as the target shape for the planning phase, not as a day-one blocker for reactive avoidance.

Planning-phase terrain traces should move to a more general plot payload shape:

```python
plot = {
    "overlay_curves": [
        {"id": "reference_idealized", "kind": "reference", "label": "...", "xs": [...], "ys": [...]},
        {"id": "reference_terrain", "kind": "reference", "label": "...", "xs": [...], "ys": [...]},
        {"id": "ballistic_cutoff", "kind": "ballistic", "label": "...", "xs": [...], "ys": [...]},
    ],
    "overlay_regions": [
        {"id": "obstacle_launch_ridge", "kind": "obstacle", "x0": ..., "x1": ..., "label": "..."},
    ],
    "sample_channels": {
        "terrain_clearance_min": [...],
        "terrain_time_to_intercept": [...],
        "terrain_mode": [...],
    },
}
```

Compatibility guidance:

- existing `ballistic_curve` / `reference_curve` fields can remain as convenience aliases in the reactive-first phase
- the viewer should render from `overlay_curves` once present
- report-mode traces must carry terrain sample channels directly
- do not rely on debug-only control logs for terrain analysis

### Controller-authored references

Once terrain-aware boost planning exists, the terrain-aware reference curve must be emitted by the bot/controller at runtime.

Do not reconstruct it afterward from the flown path or from incomplete state snapshots. The post-run viewer can still derive helpful comparison curves, but the terrain-aware route that the planner actually intended should be stored as first-class trace data.

Event additions to trace/plot output:

- `reactive_avoid_start`
- `reactive_avoid_clear`
- `terrain_threat`
- `terrain_cutoff_veto`

Planning-phase event additions:

- `terrain_replan`

### Event semantics

Terrain events are not all one-shot milestones.

The trace/event model should support repeated terrain events by giving each event a unique runtime id or sequence number. Event identity should not be just `(actor_uid, name)`.

Recommended event payload fields:

- `id`
- `name`
- `time_s`
- `x`
- `y`
- `phase`
- `sequence`
- optional metadata payload

Practical guidance:

- `terrain_replan` may occur multiple times
- `terrain_threat` should only emit on threshold crossing or state transition, not every frame
- `reactive_avoid_start` / `reactive_avoid_clear` should pair cleanly in logs and plots

Important rule once planning lands:

- the terrain-aware reference curve should be captured into the trace payload at runtime
- do not recompute it later in the viewer from incomplete state

That keeps run-detail pages faithful to the actual controller decision.

## Benchmark policy

Recommended rollout:

1. Add the new `terrain` root with `observe_only` policy while the controller is still terrain-blind.
2. Promote a small reactive-only smoke subset to `normal` once the read-only terrain API and shared reactive guard land.
3. Keep `hybrid` and `planning` cases `observe_only` until boost planning exists.
4. Expand quick/full packs only after the plots and telemetry make failures easy to interpret.

## Implementation phases

1. Bot API
   - add `TerrainQuery`
   - add `BotEnvironment`
   - inject it once during setup
2. Scenario root
   - add `terrain`
   - implement explicit scenario catalog and obstacle generators
   - start with reactive-only normal scenarios
3. Reactive avoidance
   - add shared short-horizon terrain threat evaluator
   - wire it into both `boost` and `terminal`
4. Minimal trace/plot support
   - record reactive terrain events
   - record threat/clearance sample channels
   - surface obstacle regions and reactive markers in the existing viewer
5. Boost planning
   - add terrain-aware route shaping on top of the full terrain query
6. Richer trace/plot support
   - record terrain-aware reference curves
   - move viewer rendering toward generalized overlay curves/regions
7. Benchmark packs
   - curate smoke, quick, and full scenario sets from the explicit catalog

## Open questions

- After reactive-only v1, does terminal need any limited terrain-aware replanning beyond guard-only behavior?
- Should obstacle width/height stay fully internal to named cases, or eventually become selector layers?
- Do we want a shared generic clearance metric in results, analogous to `boost_cutoff_*`, for terrain scenarios?
