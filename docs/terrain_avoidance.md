# Terrain Avoidance Design

Planning note for terrain-aware transfer scenarios, bot APIs, and trace/plot requirements.

## Problem statement

Current transfer benchmarks intentionally ignore obstacle handling:

- `boost:*` only varies route family, route tier, and cargo weight.
- The base terrain in `boost` is either flat or a single uniform slope.
- Runtime bot sensors expose only local terrain state under the ship plus a short-range proximity contact.

That was the right simplification for the current boost and terminal rebuilds, but it is now the main gap:

- `boost` needs enough terrain information to plan a route that clears obstacles.
- execution still needs a reactive terrain guardrail when the flown path drifts away from that safe route.
- Terrain scenarios need to explain failures, not just report `crashed`.

This doc proposes the first terrain-aware API and scenario model without breaking the bot/engine boundary.

## Goals

- Expose the full terrain to bots through a read-only query interface.
- Keep per-frame sensor snapshots lightweight on the hot path.
- Split terrain handling into:
  - long-horizon terrain-safe routing during `boost`
  - short-horizon reactive guardrails during execution
- Add a curated terrain scenario catalog that covers both planning and reactive behaviors.
- Make trace/plot outputs visually explain why a terrain-aware run passed or failed.

## Non-goals

- Do not fold terrain obstacles into the existing public `boost:*` selector root.
- Do not expose mutable engine internals or physics colliders directly to bots.
- Do not start with randomized obstacle fuzzing or a giant parameter cross product.

## Refined Navigation Model

Assumptions for the current design pass:

- 1D static terrain only
- no overhangs or side caves
- no specially designed traps such as deep wells
- the real objective is robust point-to-point transfer between arbitrary sites

Primary navigation ownership should be:

- `boost` owns terrain-aware route choice
- the planned / idealized transfer should already clear terrain if followed nominally
- `terminal` should inherit a safe corridor rather than solve a second terrain-planning problem

This changes the definition of "reactive avoidance."

Reactive avoidance is not "whatever only needs a quick correction."

Reactive avoidance means:

- the primary pathing / planning / guidance strategy remains valid
- terrain becomes hazardous only because the executed trajectory drifts away from that valid nominal plan
- the required terrain response is obvious and one-sided
- once terrain danger is gone, the bot can resume the same primary objective without significant replanning or a different route class

Another useful way to state it:

- reactive avoidance preserves the same mission objective
- reactive avoidance preserves the same broad route class
- terrain handling is expressed as a temporary control tradeoff inside that mission, not as a new plan

For v1, the most important "allowed" tradeoffs are:

- trade lateral progress for vertical clearance
- trade descent commitment for terrain clearance
- trade overshoot margin for earlier recovery back into the target corridor

The corresponding "not reactive" cases are the ones where terrain handling requires:

- a deliberately different transfer arc
- a different handoff strategy owned by another phase
- an intentional temporary objective other than "keep progressing toward the same target"

The size or duration of the terrain response does not matter by itself. A longer terrain-following segment can still be reactive if it does not conflict with the primary objective and does not require a new planning strategy.

Examples:

- `flat:far`: the nominal route is still a valid point-to-point transfer, but overshoot / fly-back drift can hit a target-side backstop
- `downhill:*`: the nominal descent is still the correct one, but execution error can slightly clip a late shoulder
- `climb:high:heavy`: the intended route family may still be correct, but low thrust margin can let the ship drift into terrain during the slow climb

The key distinction is not obstacle size. The key distinction is whether terrain handling changes the primary navigation strategy.

Implication for v1:

- reactive terrain scenarios should be execution-guardrail cases
- scenario acceptance should be based on "resume nominal guidance without replanning," not on "small correction"
- cases where terrain effectively forces a new route class belong in `planning` or `hybrid`, even if the terrain feature itself looks small

Additional design consequences:

- v1 reactive terrain should be built around common execution deviations, not around arbitrary obstacle silhouettes
- the scenario question should be "what drift mode does this terrain punish?" before "what obstacle shape is this?"
- terminal-side or target-side hazards are much cleaner reactive cases than source-side hazards because they usually do not change the boost-owned route class
- climb terrain is still important, but most interesting climb terrain belongs in `hybrid` or `planning`, not the first reactive pack

More accurate reactive categories:

- `terrain_follow`
  - terrain runs close to the intended corridor for a meaningful segment
  - the reactive behavior is "delay targetward progress just enough to maintain clearance, then resume the same cutoff / target objective"
  - this can last a while and still be reactive if it does not create a new route class
- `descent_clip`
  - the nominal descent family is still correct, but execution drift can clip a late shoulder or slope break
  - the reactive behavior is "delay descent commitment or lateral braking just enough to clear the shoulder, then resume the same descent objective"
- `containment_backstop`
  - the nominal route remains valid, but overshoot / fly-back / lateral drift can hit terrain outside the intended landing corridor
  - the reactive behavior is "do not drift farther outward than necessary; stay target-homing while recovering back inside the corridor"

Under this framing, reactive terrain is about whether terrain safety stays aligned with the current mission objective, not about whether the correction is brief.

### Mission-preserving tradeoffs

This is the most compact way to think about the current reactive terrain pack:

- `backstop`
  - still home toward the same target
  - do not intentionally overshoot as a terrain strategy
  - make a containment/braking tradeoff so outward lateral error does not become a terrain collision
- `clip`
  - still descend toward the same target
  - do not intentionally take a different route around the shoulder
  - make a local descent-timing / lateral-braking tradeoff so the ship clears the bump before committing downward
- `boost_clearance`
  - still boost toward the same target and same broad ballistic handoff
  - do not intentionally choose a different transfer class
  - make a local vertical-vs-horizontal tradeoff so the ship clears the source-side rise before resuming stronger targetward motion

This framing is useful because it describes the reactive problem in control terms instead of geometry terms.

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

## Prototype findings

An unmerged reactive-terrain prototype was explored after the level/catalog redesign.

It should be treated as research, not as a hidden implementation to resume blindly.

### What changed in the prototype

The prototype added a bot-side terrain guard around `pdg` with four main pieces:

- setup-time terrain/target context injected into the bot
- a shared `pdg_terrain` helper that evaluated short-horizon terrain threats
- a pre-controller stage override hook
- a post-action terrain guard plus terrain-specific telemetry / plot markers

The threat model used:

- a passive ballistic probe
- a hold-current-acceleration probe
- short-horizon terrain intercept prediction
- simple hazard classification (`clearance` vs `containment`, and later scenario-driver-specific behavior)

This was a reasonable first architecture pass. It identified the right high-level hook points:

- setup-time environment injection
- threat evaluation before stage routing
- post-controller action arbitration
- explicit terrain telemetry in traces and plots

### What worked

`containment_backstop` was the strongest case.

Why it worked:

- it naturally fits a short-horizon execution guardrail
- the nominal route remains valid
- the terrain problem is "do not continue outward into the wall" rather than "invent a new route"
- a terminal-side braking / containment bias is a natural response

The prototype also proved that terrain observability itself is valuable:

- terrain threat markers made scenario failures much easier to reason about
- separating setup-time terrain access from per-frame sensors was the right API boundary

### What did not work

`descent_clip` and `terrain_follow` did not settle under the same reactive model.

Observed failure modes:

- a generic "impending collision" probe is a poor model for `terrain_follow`
- generic thrust-floor / upright-bias responses are too weak or too ambiguous for `descent_clip`
- some early "successful" `clip` runs only worked by making `boost` own the shoulder, which is directionally wrong for this scenario family

The important lesson:

- `backstop` is a true reactive containment case
- `clip` is not just "another clearance event"
- `follow` is not primarily an imminent-collision problem at all

### What was directionally wrong

The prototype drifted into a bad shortcut for `clip`:

- `boost` stayed active until the post-cut ballistic path cleared the shoulder
- this solved the scenario numerically in some versions
- but it changed scenario ownership from terminal/coast-side reactive handling into boost-side terrain planning

That is not the behavior we want `clip` to represent.

The prototype also over-relied on "collision soon" as the core signal for `follow`.

That is the wrong abstraction for climb terrain-follow. The problem is not simply "will I hit terrain soon?" It is "am I still inside a safe terrain-relative corridor while pursuing the same climb objective?"

### Current interpretation of the results

The bot-side prototype should not be resumed as-is.

What it proved:

- the infrastructure boundary is sound
- the terrain scenarios are useful
- `backstop` is a good first reactive behavior target

What it did not prove:

- that one generic reactive terrain guard can solve all three v1 terrain cases
- that `clip` and `follow` are purely post-plan collision-avoidance problems

### Strategy change

The next design pass should treat the three terrain cases as different control problems:

- `containment_backstop`
  - terminal-side containment / braking
  - this is the best first true reactive implementation target
- `descent_clip`
  - descent corridor protection
  - this should only be considered reactive if the nominal handoff is already terrain-safe
- `terrain_follow`
  - terrain-relative corridor tracking
  - this likely needs a clearance-margin or corridor model, not just intercept prediction

Most importantly:

- reactive terrain handling should guard a terrain-safe nominal strategy
- it should not substitute for missing terrain-aware route choice

Useful simplification: narrow reactive behavior into small scenario-aligned primitives instead of one generic guard:

- `containment_backstop`
  - mostly lateral containment / braking
- `descent_clip`
  - mostly descent veto / descent-floor behavior
- `terrain_follow`
  - mostly terrain-clearance floor / terrain-margin tracking

This is simpler than a universal terrain guard and more faithful than trying to force every reactive case into a lateral-only response.

Implication:

- `backstop` can likely be implemented as a standalone reactive guard
- `clip` and `follow` may require some amount of nominal terrain-aware boost / handoff shaping before a reactive layer makes sense

### Recommended next steps

Do not restart with "generic terrain guard for all scenarios."

Instead:

1. Keep the committed terrain/environment scaffolding as the base.
2. Reintroduce terrain behavior one scenario family at a time.
3. Start with `backstop` only.
4. Add scenario-specific instrumentation before trying to tune control behavior again:
   - `backstop`: corridor exit, outward velocity, wall intercept time, overshoot distance
   - `clip`: first descent-arc / shoulder intersection, descent start position, time from handoff to shoulder intrusion
   - `follow`: minimum terrain clearance across the follow span, time below clearance floor, peak clearance deficit
5. Run an explicit feasibility check for `clip`:
   - if a normal boost/handoff can still leave a terrain-safe descent corridor and only local descent delay is required, keep it reactive
   - if not, redesign the scenario or move it out of reactive v1
6. Treat `follow` as a boost execution primitive:
   - terrain-relative clearance-margin keeping
   - not a late terminal collision guard
7. Only after these behaviors make sense separately should they be generalized into a shared terrain layer again.

More concrete ownership guidance for the next attempt:

- `containment_backstop`
  - first implementation target
  - terminal-side containment / braking primitive
  - best candidate for a divert-feasibility check layered onto the existing terminal gate
- `descent_clip`
  - keep only if feasibility analysis confirms it is truly a local descent-corridor problem
  - otherwise move it out of reactive v1 instead of forcing the bot to fake it
- `terrain_follow`
  - boost-phase terrain-margin primitive
  - preserve the same climb objective while keeping clearance over the terrain-follow segment

Implementation bias for the next pass:

- do not start with a new generic terrain controller
- add a lightweight terrain-feasibility margin beside the existing terminal gate
- use that first for `backstop` only
- keep the runtime probe on a fixed sampling budget and out of `BOOST`
- do not let terrain instrumentation expand the hot path on non-terrain runs
- treat `clip` and `follow` as follow-on problems after `backstop` is shown to work cleanly

Updated lesson from the first `backstop` divert prototype:

- the right safety question is not "does the passive arc directly hit the wall?"
- the right safety question is "can terminal still recover back inside the safe corridor before wall-side terrain becomes binding?"

So the next `backstop` pass should use a corridor-recoverability trigger, not a direct wall-penetration trigger.

Additional lesson from the trace review:

- exact corridor exhaustion is also too late

### Updated backstop status

The current `backstop` prototype now has a cleaner generic shape:

- target-side terrain is summarized once at setup
- lateral containment only considers terrain that looks like a barrier, not just any rise beyond target
- the useful generic boundary test is:
  - steep initial rise
  - followed by a flat or nearly flat tail
- runtime arming exits immediately when neither side of target matches that containment shape

This matters because the earlier generic pass falsely armed on normal uphill pads:

- ordinary `boost:climb:*` target-side terrain can be steep near the pad
- but it keeps rising afterward, so it is not a `backstop`
- once the runtime prefilter required a barrier-like tail, false normal-run probes dropped back to zero

Current practical status:

- `terrain:reactive:terminal_backstop` is solved
- `terrain:reactive:terminal_clip` is also solved with a separate coast/terminal primitive
- normal quick-pack behavior is unchanged
- normal quick-pack probe count is zero outside the actual backstop case
- normal quick-pack compute is back near baseline

So the current recommendation stands:

- keep `backstop` as the active containment response
- keep `clip` as a separate descent primitive
- keep generic geometry-based arming
- do not widen to `follow` until it has its own control primitive

For the failed `backstop` seeds, a max-braking stop-distance margin stays positive until the final seconds and only goes negative essentially at impact.

So the next containment trigger should arm on a shrinking positive recoverability buffer, not only when the state is already mathematically unrecoverable.

That also implies the response should be a real temporary containment mode in terminal:

- stronger inward braking authority
- temporary descent suppression while wall-side containment is unresolved
- release once outward velocity and corridor buffer recover

Updated lesson from the next `backstop` pass:

- a blended recoverability-buffer trigger still did not separate the good and bad seeds cleanly enough
- projected corridor overshoot at target-height crossing separated them better
- the working shape was:
  - keep moderate overshoot seeds on `latest_safe`
  - move only the worse overshoot seeds into `terrain_divert`
  - use an explicit temporary terminal containment override after that handoff

So the current best `backstop` strategy is:

- gate on projected corridor overshoot
- keep ownership in `COAST` / `TERMINAL`
- once armed, use a dedicated terminal containment mode instead of a small additive bias

Current review note:

- the resulting containment arc can still run visibly close to the wall
- that is expected under this trigger, because the controller is protecting corridor re-entry, not trying to maximize raw wall clearance
- so "close to the wall" by itself is not the main failure signal for this pass
- the more important question is whether the maneuver stays within an acceptable reactive envelope instead of turning into a new route class

### Implementation pass: summary-based generic arming (2026-04)

The current bot-side terrain pass removes scenario metadata from the runtime trigger path, but it does not try to solve every terrain family with one response.

Architecture:

- **Setup-time terrain summary** (`BotEnvironment.terrain_summary`):
  - target ground height
  - first elevated boundary to the left/right of target above a fixed local threshold
- **Cheap runtime arming** (`evaluate_terrain_divert_probe`):
  - no ballistic terrain sampling in the hot path
  - uses projected landing side, precomputed corridor boundary, projected corridor overshoot, and outward velocity
  - currently only arms a `lateral_containment` response
- **Containment override** (`backstop_containment_override`):
  - terminal-only
  - active only after the terminal gate explicitly enters `terrain_divert`
  - brakes inward relative to the target-side elevated boundary while keeping enough vertical support to stay recoverable

Key findings from this pass:

1. **Terrain-derived boundaries are the right generic primitive for containment.**
   The useful geometry is "where does terrain first rise past the target corridor?", not "does this scenario declare a wall?"

2. **A cheap generic guard can be separated from the response law.**
   The runtime trigger can be generic and terrain-derived while the active response is still just the containment primitive. This avoids hardcoding specific selector names while still admitting different later responses for `clip` and `follow`.

3. **The current containment response is still stronger than a minimal guardrail.**
   It lands `backstop` reliably, but the resulting terminal arc is still materially larger than the baseline route. That remains a quality question, not a correctness question.

4. **The broad always-on trajectory-sampling probe was a bad shape.**
   Replacing it with setup-time summaries plus O(1) corridor arming kept `backstop` solved while restoring exact behavioral isolation on the normal quick pack.

5. **The compute issue is now under control for the current containment path.**
   The later barrier-shape prefilter brought the normal quick-pack compute back to near parity while keeping `backstop` solved.

### Implementation pass: simple descent-clip primitive (2026-04)

The next successful terrain step did not extend the `backstop` response. It added a separate `clip` primitive with its own control shape.

Architecture:

- **Enable path**:
  - currently scoped to `hazard_driver=descent_clip`
  - this is narrower than the `backstop` arming layer on purpose
- **Short-horizon clip probe** (`evaluate_terminal_clip_probe`):
  - active only in `COAST` / `TERMINAL`
  - rolls out the near path toward target for a fixed horizon
  - checks whether that near path intersects terrain before target
- **Clip response** (`clip_targetward_override`):
  - does not modify `BOOST`
  - forces immediate terminal entry when the short-horizon path is already unsafe
  - then adds a targetward, lift-preserving mix-in while the local path still clips the shoulder

Current practical status:

- `terrain:reactive:terminal_clip` is solved on the focused 10-seed pack
- it also resolves the quick observe-only `clip` slice
- normal quick-pack behavior remains unchanged
- quick normal-pack compute remains effectively unchanged relative to baseline

Current quality caveat:

- on the solved `clip` seeds, terminal entry now happens almost immediately after boost cutoff
- that is still coast/terminal ownership, not boost-side planning
- but it means the current solution reads more like immediate terminal handoff plus local correction than long passive coast followed by a late pulse

So the current recommendation is:

- keep `clip` as a separate descent primitive
- do not force it into the `backstop` containment path
- only revisit generalization after `follow` has its own primitive too

### Acceptance criteria for the next attempt

Do not judge the next prototype by raw success rate alone.

Also require:

- no route-class changes for scenarios meant to be reactive-only
- bounded reference-gap or equivalent route-deviation metrics
- clear agreement between scenario ownership and controller ownership
- scenario-specific reasoning in traces and plots so "why it passed" is visible

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

Reactive avoidance is an execution guardrail, not a second path planner.

Responsibilities:

- monitor short-horizon terrain threat during execution
- detect when the flown path has drifted into a short-horizon terrain threat
- bias control upward, delay descent, or veto an unsafe cutoff when that response is obvious
- return control to the same primary guidance objective once clearance is restored

Reactive avoidance should use shared threat metrics across both phases so logs and plots stay consistent.

Example threat signals:

- minimum predicted clearance over a short forward horizon
- predicted time to terrain intercept
- required additional loft above the current reference
- whether the projected passive arc intersects terrain before the target corridor

Reactive acceptance rule:

- if the correct terrain response implies a different broad route class, that is not reactive
- if the correct terrain response can be treated as a temporary terrain-safety override around the same primary route objective, that is reactive

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
- if terrain handling requires a different mission path class, the guard should escalate to replan instead of trying to "react" its way through it

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

Long-term public selector shape:

- `terrain:<band>:<case>`

Examples:

- `terrain:reactive:terminal_backstop`
- `terrain:reactive:terminal_clip`
- `terrain:reactive:boost_clearance`
- `terrain:planning:mid_mesa`

Rationale:

- existing `boost:*` selectors are already stable and used broadly
- obstacle handling deserves its own benchmark policy and pack curation
- this keeps clear-terrain regressions and terrain-aware regressions separable

Selector cleanup follow-up:

- the current implemented terrain stack is deeper than the actual user-facing choice set
- the meaningful user-facing dimensions are:
  - avoidance band, for example `reactive` / `planning`
  - hazard case, for example `terminal_backstop`, `terminal_clip`, `boost_clearance`
- route family, route tier, and weight tier should become scenario metadata or backward-compatible aliases rather than permanent public selector layers
- the current deep selectors can remain as implementation-time aliases during the transition, but they should stop being the primary public shape

## Scenario catalog design

Start with an explicit scenario catalog, not a giant generated matrix.

Each scenario should carry intent metadata directly in the catalog:

```python
@dataclass(frozen=True)
class ObstacleSpec:
    kind: Literal["ridge", "shoulder", "mesa", "backstop"]
    x_fraction: float
    width: float
    height: float
    shoulder_width: float = 0.0
    target_offset: float = 0.0
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
    reactive_contract: Literal["execution_guardrail", "hybrid", "planning"]
    hazard_driver: str
    reactive_trigger: Literal["execution_drift", "nominal_path_invalid"]
    resume_without_replan: bool
    primary_navigation_owner: Literal["boost", "terminal"]
    nominal_route_must_clear: bool
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

That means the initial normal-pack scenarios should only ask the controller to solve execution-drift terrain hazards without changing the primary navigation strategy.

Rules for v1 normal scenarios:

- exactly one obstacle per scenario
- the nominal terrain-aware route should already clear terrain if followed well
- terrain should become hazardous only when execution drifts away from that nominal route
- the terrain response should not require a different route class or a new planning objective
- prefer cases where "avoid terrain, then resume the same plan" is obviously the right behavior
- encode the expected drift mode directly in scenario metadata so later plots and controller traces can explain why the scenario exists

Do not put these in the initial normal pack:

- boost-side obstacles that demand sustained route reshaping
- late uphill cases where the terminal horizon is too short and terrain handling effectively changes the route class
- broad mesas that require a sustained higher route
- double-ridge scenarios
- hard margin-limited `climb:high:full` planning cases

Those belong in observe-only coverage until boost planning exists.

### Feature families by route type

Different baseline families should prefer different obstacle primitives.

- `flat`
  - prefer target-side backstops and broad flat-top obstacles (`mesa`)
  - the reactive flat case should punish overshoot / fly-back drift, not block the nominal landing line itself
  - broad flat-top cases that require route shaping should use `mesa`, not a reactive backstop label
- `downhill`
  - prefer `shoulder` cases over standalone ridges
  - a shoulder is a local slope hold / flatten / break that intrudes into the expected descent corridor
- `climb`
  - prefer `shoulder` cases over standalone ridges
  - a shoulder is a local roll-up or slope extension that makes a previously safe-looking climb/descent commitment unsafe

This keeps the terrain shapes natural for the underlying route family instead of dropping the same obstacle silhouette onto every baseline.

Behavior-first mapping:

- `flat`
  - strongest reactive case is usually `containment_backstop`
  - pure terrain-follow cases are weak on flat terrain because there is no natural slope corridor to track
- `downhill`
  - strongest reactive case is usually `descent_clip`
  - some downhill cases can also behave like short terrain-follow segments
- `climb`
  - strongest reactive case is usually `terrain_follow`
  - late terminal obstacles are usually poor reactive cases because they quickly change the route class instead of just guarding execution drift

### Baseline route coverage

Use a small representative baseline set:

- `flat:far`
- `downhill:mid`

Reactive-first normal packs should start there.

Keep these for planning-phase expansion:

- `flat:mid`
- `climb:mid`
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

- encode public terrain cases as named curated behaviors first, for example `terminal_backstop`, `terminal_clip`, `boost_clearance`, `mid_mesa`, `double_ridge`
- keep width/height/asymmetry inside the scenario definition unless they become stable user-facing concepts later

This avoids a brittle selector explosion while the controller is still evolving.

For the current reactive trio, the intended public names are:

- `terminal_backstop`
  - terminal/coast containment while still target-homing
- `terminal_clip`
  - terminal/coast descent-commitment delay over a late shoulder
- `boost_clearance`
  - boost-phase progress-vs-clearance tradeoff over a source-side rise

### V1 implementation scope

The actual v1 level implementation should stay narrower than the long-term design space:

- only ship the three guardrail scenarios that clearly match the refined definition
- keep scenario metadata explicit about `hazard_driver`, `reactive_trigger`, and who owns primary navigation
- do not keep generic climb/boost obstacle shape logic in the level code just because planning-phase scenarios might need it later
- when planning or hybrid terrain is added, extend the terrain builder from those concrete use cases rather than preserving speculative branches from day one

### Determinism requirements

Each named obstacle case should resolve to deterministic geometry for a given selector and seed:

- route geometry must still follow the selected baseline family/tier
- obstacle positions should use an explicit stable anchor rule, for example route-progress fractions or target/source-relative offsets, then materialize into concrete world x coordinates
- obstacle dimensions must be part of the catalog, not inferred ad hoc inside level setup
- if any obstacle dimension is randomized later, it must follow the existing benchmark median/sample rules and be recorded in scenario params

## Reactive-First Starter Set

The reactive starter set should be framed by behavior, not by obstacle silhouette.

Current implemented v1 pack:

| Selector | Avoidance band | Context / why | What to test | Plot focus |
| --- | --- | --- | --- | --- |
| `terrain:reactive:terminal_backstop` | `reactive` | `containment_backstop`: flat long-range transfer with a target-side wall that is irrelevant to a clean landing but punishes overshoot and fly-back drift. | Reactive logic should avoid the backstop without changing the primary point-to-point plan. | Target pad, backstop rise, overshoot / fly-back path, resume-toward-target behavior. |
| `terrain:reactive:terminal_clip` | `reactive` | `descent_clip`: downhill route with a target-relative late shoulder before the final drop to target. The route band should stay narrow enough that this remains one stable local cutoff-veto situation, not a mix of local and route-reshaping regimes. | Reactive logic should avoid diving into the shoulder or committing too early into the final drop. | Downhill terrain line, shoulder edge, terminal entry, descent delay or pull-up. |
| `terrain:reactive:boost_clearance` | `reactive` | `boost_clearance`: flat transfer with a steep source-side rise that punishes over-prioritizing targetward progress immediately after launch. | Reactive logic should trade horizontal progress for vertical clearance, clear the rise, then resume the same targetward transfer without replanning. | Source-side rise, early boost path, clearance margin over the rise, resume-to-reference behavior after clearing it. |

Deferred from v1:

- `climb:terminal_shoulder`
- `boost_table`
- `mid_table`
- `boost_shoulder`

Why `climb:terminal_shoulder` moved out:

- on the climb family, the late terminal window is too short for even a modest shoulder to stay purely guardrail-like
- once the terrain feature meaningfully changes the climb profile or terminal-entry shape, the scenario is no longer testing reactive execution safety
- that makes it a better future `hybrid` or `planning` case than a v1 reactive scenario

Why the current `terrain:reactive:boost_clearance` shape fits better:

- it isolates the intended control tradeoff directly: give up targetward progress temporarily to buy clearance
- it keeps ownership in `BOOST`, where that tradeoff actually lives
- it avoids conflating the terrain-follow problem with a globally steeper uphill route family
- a terrain-blind bot should clip the source-side rise by chasing horizontal progress too early, while a terrain-aware bot can stay more upright, clear the rise, then resume the same transfer

Current practical status after the level redesign:

- `backstop` remains solved by the current bot
- `clip` remains solved by the current bot
- `boost_clearance` is now solved with a dedicated boost-phase `progress_clearance` primitive
- the current reactive trio is therefore covered by three distinct control shapes:
  - terminal containment for `backstop`
  - coast/terminal descent correction for `clip`
  - boost-phase progress-vs-clearance control for `boost_clearance`

Naming/design guidance from the current definition:

- the public scenario name should describe the mission-preserving tradeoff first
- geometry should explain the case, but not be the whole identity of the case
- current internal shorthand maps cleanly to the public names:
  - `backstop` -> `terminal_backstop`
  - `clip` -> `terminal_clip`
  - `follow` -> `boost_clearance`
- the public selector shape is now `terrain:reactive:*`; route family, route tier, and weight tier remain scenario metadata only
- if variants appear later, prefer behavior-first qualifiers such as:
  - `boost_clearance:source_rise`
  - `clip:late`
  - `backstop:target`
  rather than re-exposing a deep family / route / weight stack when those are not true user-facing choices

Current selector/catalog structure:

1. The public terrain selector root is flattened to `terrain:<band>:<case>`.
2. Terrain scenarios carry explicit public ids in the catalog instead of reconstructing them from family/tier/weight fields.
3. Route family, route tier, weight tier, and detailed geometry are scenario metadata only.
4. The current reactive public cases are:
   - `terrain:reactive:terminal_backstop`
   - `terrain:reactive:terminal_clip`
   - `terrain:reactive:boost_clearance`
5. Internal hazard-driver/control names stay distinct from the public case names when useful:
   - `containment_backstop`
   - `descent_clip`
   - `progress_clearance`
6. Registry defaults, wildcard benchmark expansion, README examples, and terrain tests now use the flattened selector shape.
7. The old deep terrain selectors are removed rather than preserved as long-term compatibility paths.

Important evaluation note:

- a reactive guardrail scenario does not need to fail on every seed with a terrain-blind bot
- if a particular seed stays inside the nominal safe corridor, it may still land cleanly without reactive intervention
- the useful signal is whether terrain creates failures on drift-prone executions without requiring a different route class
- this is different from planning scenarios, where the nominal path itself should be invalid without terrain-aware routing
- the terrain-blind bot can therefore show a mix of clean landings and terrain crashes in the same reactive scenario without invalidating the scenario design

Scenario redesign guidance:

- add:
  - more reactive cases framed by the allowed tradeoff, not by arbitrary silhouettes
  - source-side rise / shelf cases that explicitly test progress-vs-clearance tradeoffs
  - late descent-brow cases that explicitly test descent-commitment delay
  - target-side containment cases that explicitly test corridor recovery without route change
- keep:
  - flat target-side backstops as containment/overshoot guardrails
  - downhill terminal shoulders as descent-clip guardrails
- change:
  - judge reactive validity by alignment with the primary objective, not by obstacle size or shortness of correction
  - describe scenarios primarily by hazard behavior (`progress_clearance`, `descent_clip`, `containment_backstop`) and only secondarily by geometry
- remove from reactive v1:
  - source-side tables and shoulders that demand sustained route reshaping
  - late climb obstacles that effectively define a new terminal strategy

Additional reactive cases worth considering later:

- `follow` variants
  - slightly later source-side rise on flat or mild downhill terrain
  - short source shelf that requires staying upright longer before resuming targetward motion
- `clip` variants
  - flatter terminal brow instead of a full shoulder
  - slightly wider late shoulder to test a longer descent-delay window without changing route class
- `backstop` variants
  - lower, closer target-side barrier that punishes shallow overshoot
  - mirrored target-side barrier on the opposite side of the corridor for return-from-the-other-side cases

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
