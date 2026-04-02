# Terrain Guard Research

Research notes on collision avoidance with bounded 2D rotatable thrust.

Context: the PDG bot needs a per-frame reactive terrain guard that answers "given my current state and control authority, can I avoid hitting terrain?" without solving a full trajectory optimization.

## Problem statement

The lander has:

- 2D rotatable thrust (variable magnitude + angle)
- bounded thrust: `rho_min <= ||T|| <= rho_max`
- static terrain heightfield
- gravity

The guard must determine per-frame whether the current trajectory is on a collision course with terrain, and whether the bot has enough control authority to avoid it.

The challenge: because thrust is rotatable, "max braking" is not a scalar. Thrust allocated to lateral braking reduces vertical control, and vice versa.

## Key concepts from guidance theory

### Zero-Effort Miss (ZEM / ZEV)

ZEM answers: "if I apply zero control from now until time `t_f`, where will I be?"

Given current state `(r, v)`, gravity `g`, and time-to-go `t_go`:

```
r_ballistic(t_go) = r + v * t_go + 0.5 * g * t_go^2
```

ZEM is the miss distance between this ballistic endpoint and the desired target:

```
ZEM = r_target - r_ballistic(t_go)
```

ZEV is the velocity miss:

```
ZEV = v_target - (v + g * t_go)
```

The optimal energy-minimum correction acceleration is:

```
a_cmd = (6 / t_go^2) * ZEM - (2 / t_go) * ZEV
```

This is a closed-form feedback law (no solver needed). It is the same structure as proportional navigation with time-varying gains.

For terrain avoidance, ZEM itself is the diagnostic: if the zero-effort trajectory intersects terrain, the bot needs to act. The question is whether it *can* act enough.

### Divert envelope

The divert envelope is the set of positions reachable from the current state given bounded thrust over a time horizon.

At each future time `t`, the ballistic (zero-effort) position is:

```
r_ballistic(t) = r + v * t + 0.5 * g * t^2
```

The maximum position deviation from the ballistic endpoint achievable with bounded thrust `a_max` is:

```
delta_r_max(t) = 0.5 * a_max * t^2
```

This forms a circle (in 2D) of radius `delta_r_max` centered on `r_ballistic(t)`. The union of these circles over all `t` in `[0, T]` is the divert envelope.

The terrain guard question becomes: at each sample time along the ballistic arc, does the reachable circle include any position that clears terrain?

### Coupling between axes

For a vehicle with TWR > 1 (can hover), the available lateral authority while maintaining vertical equilibrium is:

```
a_lateral_available = sqrt(a_max^2 - g^2)
```

This naturally captures the coupling: full thrust cannot go lateral because some must fight gravity.

More generally, if the vehicle needs `a_y` of vertical acceleration, the remaining lateral authority is:

```
a_lateral = sqrt(a_max^2 - a_y^2)
```

For a conservative terrain clearance check, the relevant vertical acceleration is `g` (hover). For a more aggressive check accounting for vertical braking needs, `a_y` should include the vertical deceleration required to arrest downward velocity.

### Velocity cost correction

The raw divert envelope (`0.5 * a_max * t^2`) overstates reachability because it ignores the cost of arresting current velocity. A conservative correction:

```
effective_divert(t) = 0.5 * a_net * t^2 - |v_component| * t
```

This accounts for the fact that some of the available acceleration budget must be spent stopping, not diverting.

### G-FOLD terrain constraint (glide slope cone)

The convex optimization approach uses a simple geometric constraint:

```
r_y(t) >= tan(gamma_gs) * ||r_x(t)||
```

The vehicle must stay inside an inverted cone from the landing site. This is a second-order cone constraint compatible with SOCP solvers. It prevents steep descent angles that could lead to terrain collision.

For the reactive guard, the glide slope concept is less directly useful because it requires a known landing target and does not handle arbitrary terrain shapes. But it illustrates that terrain avoidance can often be expressed as a simple geometric constraint.

## Practical per-frame algorithm

### Divert-envelope terrain feasibility check

```
for each sample time t in [dt, 2*dt, ..., T]:
    # ballistic position at time t
    r_ball = r + v * t + 0.5 * g * t^2

    # terrain height at ballistic x
    h_terrain = terrain.sample_height(r_ball.x)

    # passive clearance (zero effort)
    clearance_passive = r_ball.y - h_terrain

    # max vertical position correction achievable by time t
    # conservative: uses a_max - g (net upward authority)
    delta_y_max = 0.5 * (a_max - g_mag) * t^2

    # clearance achievable with max effort
    clearance_max_effort = clearance_passive + delta_y_max

    # track worst margin
    margin = min(margin, clearance_max_effort)

    # track first ballistic intercept
    if clearance_passive < 0 and first_intercept_t is None:
        first_intercept_t = t
```

Properties:

- O(n_samples) per frame, no solver
- conservative: if this says feasible, it truly is (assuming instant rotation)
- `first_intercept_t` gives urgency
- `min_margin` gives a continuous safety metric for telemetry

### Refinements

**Velocity cost**: subtract `|vy_down| * t` from `delta_y_max` to account for arresting downward velocity before diverting upward.

**Lateral divert**: for lateral containment (backstop), use `a_lateral_available = sqrt(a_max^2 - g^2)` and check horizontal reachability instead of vertical.

**Directional projection**: for arbitrary terrain shapes, project the divert capability along the terrain normal at the intercept point rather than purely vertical or lateral.

**Non-vertical terrain (slopes, shoulders)**: the check naturally handles these because `terrain.sample_height(r_ball.x)` returns the actual terrain height at the ballistic x-position. No special casing needed for terrain shape.

## Design implications for pylander

### Why the prototype failed

The prototype used passive ballistic intercept as the threat signal. During normal coast toward a target with a backstop behind it, the passive arc often intersects the backstop terrain. This is expected and not dangerous because the bot plans to brake and land before reaching it.

The divert-envelope approach fixes this: during normal coast, the max-effort trajectory easily clears the backstop (the bot has plenty of authority to stop). The guard only fires when that margin shrinks toward zero, which is exactly when the bot is drifting into real danger.

### Why this is generic

The algorithm does not need to know about backstops, shoulders, or terrain-follow segments. It asks one question: "can I avoid terrain?" The answer depends on the terrain shape, the bot's state, and the bot's control authority. Different terrain shapes naturally produce different threat profiles without scenario-specific logic.

### Coupling resolution

The 2D thrust coupling is handled by using `a_max - g` (net upward authority) for vertical checks or `sqrt(a_max^2 - g^2)` for lateral checks. These are conservative bounds that account for the gravity tax on thrust authority.

For a more precise check, the divert capability could be projected along the terrain-normal direction at each sample point, splitting thrust between the gravity-opposing component and the terrain-avoidance component. But the axis-aligned conservative bounds are likely sufficient for v1.

### Where this helps the current bot

The most useful framing for `pdg` is not "replace terminal entry logic."

It is:

- keep the existing target-relative terminal gate
- add a terrain-feasibility margin beside it
- use that margin to decide whether the current coast / terminal state is still terrain-recoverable

This matters most for shallow or high-lateral-energy terminal entry.

Today the terminal gate already answers:

- "can I still brake and land on target?"

The divert-envelope check answers the missing question:

- "can I still brake and avoid terrain while doing that?"

So the technique is most relevant when terminal behavior is terrain-limited rather than merely weak in general.

Practical consequence:

- `containment_backstop`: strong fit
- `descent_clip`: only useful if the nominal handoff is already terrain-safe
- `terrain_follow`: not a terminal-entry problem first; this still wants boost-phase clearance-margin logic

### Recommended integration into `pdg`

The clean integration path is to treat divert feasibility as a lightweight terrain-aware extension of the existing terminal gate rather than a second controller.

Current `pdg` already has:

- analytic target-y crossing and ballistic projection
- a cheap coast-time terminal gate
- recoverability-based terminal tilt logic

The new piece should be a terrain-feasibility probe that runs beside those checks.

Recommended ownership:

1. `BOOST`
   - no divert-envelope terrain behavior in v1
   - keep boost terrain-blind for this pass
2. `COAST`
   - evaluate target-side terminal readiness as today
   - also evaluate terrain divert margin
   - if target gate is not urgent but terrain margin is collapsing, enter `TERMINAL` early
3. `TERMINAL`
   - keep the same terminal controller
   - use terrain divert margin as a safety / urgency signal for containment or braking bias

This keeps the implementation aligned with the current architecture instead of introducing a parallel terrain controller stack.

### Sampling strategy and compute budget

The controllable-set papers are useful conceptually, but the online check here should stay much cheaper.

Do not use full reachable-set optimization in the runtime loop.

Do not use `sample_ballistic_trajectory()` in the per-frame hot path either. It is useful for offline analysis and plotting, but it is too heavy as the default runtime probe.

The right v1 shape is a fixed-budget ballistic sample with conservative reachable corrections:

1. pick a short future horizon
2. sample a small number of points along the passive ballistic path
3. at each sample, compute passive terrain clearance
4. add a conservative reachable correction budget
5. track the worst margin and first limiting time

Suggested runtime budget:

- only active for terrain-aware levels or when terrain guard is enabled
- only active in `COAST` and `TERMINAL`
- horizon:
  - `min(4.0 s, time_to_target_y_crossing + 1.0 s, time_to_ground)`
- coarse samples:
  - `8-12`
- optional refinement:
  - if worst margin is near zero, resample `4-6` points around the worst interval
- target terrain queries per tick:
  - `<= 16`

This should be modest compared with solver work and much cheaper than iterative trajectory search.

### Conservative v1 probe shapes

Use axis-aligned conservative reachability first.

For target-side `backstop`:

- sample passive ballistic x/y
- compare against terrain at the sampled x
- use lateral reachable correction when the sampled hazard is effectively wall-like or target-side containment-dominated:
  - `a_lateral_available = sqrt(a_max^2 - g^2)`
- subtract velocity cost using outward `vx`

For more general terrain:

- use vertical clearance correction:
  - `delta_y_max = 0.5 * a_up_net * t^2 - |vy_down| * t`
- where `a_up_net` starts as `a_max - g`

Only move to terrain-normal projection after the axis-aligned version is shown to be insufficient.

### V1 implementation plan

The first divert-envelope implementation should be intentionally narrow.

Scope:

- target `containment_backstop` only
- integrate in `COAST` / `TERMINAL`
- do not change `BOOST`
- do not try to solve `clip` or `follow` in the same pass

Proposed rollout:

1. Add a small helper module, for example `bots/pdg_terrain_divert.py`.
   - input: current passive state, target position, terrain query, thrust authority
   - output:
     - `min_margin`
     - `first_limit_t`
     - `worst_x`
     - `mode` (`vertical_clearance` or `lateral_containment`)
2. Call it from the existing terminal-gate flow.
   - first use: terrain-aware early terminal entry for `backstop`
   - second use: terrain urgency telemetry in terminal
3. Export telemetry.
   - `terrain_divert_margin_min`
   - `terrain_divert_first_limit_t`
   - `terrain_divert_mode`
   - probe count / probe ms
4. Validate only on:
   - `terrain:flat:far:backstop:half`
   - quick non-terrain bundle for regression safety
5. Only after `backstop` is solid:
   - run a feasibility analysis for `clip`
   - separately design a boost-phase clearance-margin primitive for `follow`

## Prototype findings: backstop divert v1

The first implementation pass was intentionally narrow:

- new helper module: `bots/pdg_terrain_divert.py`
- fixed-budget probe beside the existing terminal gate
- scope limited to `terrain:flat:far:backstop:half`
- no `BOOST` ownership change
- terminal-side experiments only

Two control variants were tried after the probe landed:

1. a backstop-only terminal containment optimizer variant
2. a narrower terminal-side inward lateral bias

Neither changed the observed `backstop` success rate.

### What worked

- The runtime and test scaffolding is sound.
  - terrain environment injection was already in place
  - the probe integrates cleanly beside the terminal gate
  - telemetry and plot markers are now explicit instead of opaque
- Scope stayed isolated.
  - the normal quick pack success/crash totals stayed unchanged
  - `clip` and `follow` were untouched
- The probe proved one useful negative result:
  - the failing `backstop` seeds are not failing because the passive path literally penetrates the wall in the sampled divert horizon

### What did not work

- Focused `backstop` remained `4/10`.
- The gate never actually entered with `terrain_divert`.
  - failing seeds still entered on `latest_safe`
  - `bot_pdg_terrain_divert_margin_min` stayed `None`
  - `bot_pdg_terrain_divert_first_limit_t` stayed `None`
- Terminal entry geometry did not materially move.
  - failing seeds still entered terminal with projected dx around `-250 .. -320`
  - the new passes mostly reduced post-entry apex gain a bit, but did not change the success set
- The first implementation caused a real compute regression.
  - on the quick normal pack, `terminal_probe_count` went from `0` to about `104` mean per run
  - the normal quick pack avg total ms/tick regressed by about `+15%`

### Why it failed

The current probe is answering the wrong question for `backstop`.

It asks:

- "does the sampled passive path directly penetrate the wall within the short probe horizon?"

But the actual failure mode is:

- "have I already carried too much outward lateral energy to brake and re-enter the safe corridor before the wall-side terrain wins?"

That is a stopping-room / corridor-recoverability problem, not a direct passive wall-penetration problem.

Evidence from the failed seeds:

- the probe is active with `terrain_divert_mode=lateral_containment`
- `min_margin` still stays `None`
- terminal entry still happens at the normal `latest_safe` point
- projected dx at terminal entry is still large and outward (`-250 .. -320`)
- the lander then flies a long high-energy terminal arc and hits the wall side anyway

So the divert-envelope logic was directionally useful, but the specific proxy was too weak:

- lateral wall penetration is too late a trigger
- terminal entry still remains target-centric
- the small containment response is not enough once the state is already unrecoverable

There is a second important nuance from the trace review:

- even a "max lateral braking stop-distance" margin only collapses very late on the bad seeds

Example pattern from a representative failed seed:

- terminal entry happens around `x≈778`, with projected dx still around `-296`
- simple stop-distance margin versus the wall-side corridor is still large and positive for most of terminal
- it only falls into a small positive band near the final seconds
- it turns negative only essentially at the crash

That means an exact recoverability trigger of the form:

- `corridor_margin = distance_to_corridor - stop_distance`
- arm when `corridor_margin <= 0`

is also too late by itself.

So the next trigger should not be "unrecoverable already."

It should be:

- "recoverability buffer is getting too small while outward motion is still unresolved"

In practice that means:

- arm before exact corridor exhaustion
- use a configurable positive buffer, not zero
- once armed, hold a dedicated containment mode until outward velocity has been materially reduced

### Compute findings

The main compute regression did not come from successful terrain behavior.

It came from broadening terminal-gate probing across ordinary coast behavior:

- the terminal gate now times and records probe work on all coast runs
- the divert helper is called from the gate path every time the gate runs
- even when the scenario is not terrain-aware, that hot-path expansion shows up in the normal quick bundle

This means the next pass must separate:

- terrain-specific instrumentation and logic
- generic terminal-gate hot-path behavior

The cheap case has to stay cheap.

### Revised strategy

Do not continue tuning the current passive-wall-penetration probe.

For `backstop`, switch the threat model to corridor recoverability:

1. define the safe corridor boundary on the wall side
   - e.g. wall start minus body clearance on that side
2. estimate whether the current outward motion can still be arrested and brought back inside that corridor before terrain becomes binding
3. arm only when that corridor margin collapses

This keeps the question aligned with the actual failure mode:

- not "will the passive path hit the wall soon?"
- but "can I still stop the overshoot before the wall-side terrain becomes unrecoverable?"

### Recommended next implementation shape

1. Keep `backstop` as the only active terrain-control target.
2. Remove broad hot-path probe work from non-terrain scenarios.
   - do not record per-tick terminal probe timing/cost on ordinary runs by default
   - add a cheap terrain prefilter before any heavier logic
3. Replace the current `backstop` trigger with a corridor-exhaustion check.
   Candidate signals:
   - outward velocity on the wall side
   - projected impact x beyond the corridor boundary
   - stopping distance / recoverable lateral miss relative to remaining terrain-safe room
   - importantly: trigger on low recoverability buffer, not only on negative exact margin
4. Keep the response terminal-owned.
   - earlier `COAST -> TERMINAL` is acceptable
   - `BOOST` should stay terrain-blind in this pass
5. Once armed, use a dedicated containment primitive.
   - prioritize killing outward velocity
   - suppress needless descent while containment is unresolved
   - keep the landing target the same, but temporarily prioritize corridor recovery over nominal centering

The control shape should be more explicit than the first prototype attempts:

- this is not just a small lateral bias
- this is a temporary containment mode inside terminal
- likely ingredients:
  - strong inward tilt preference or clamp
  - thrust floor high enough to realize that lateral control
  - temporary descent suppression while the wall-side buffer is low
  - release once outward velocity and corridor buffer both recover

The important lesson from this prototype is:

- divert-envelope thinking is still the right direction for `backstop`
- but the first useful metric is corridor recoverability, not raw wall penetration

## Prototype findings: backstop divert v2

The second pass kept the scope narrow but changed two things:

- the gate arms from projected corridor overshoot instead of passive wall-penetration or blended recoverability margin
- terminal applies a dedicated temporary containment override instead of a small lateral bias

### What changed

The useful discriminator turned out to be the projected miss at target-height crossing.

For the original `backstop` seeds:

- landed seeds were clustered around projected overshoot of roughly `127..171m`
- crashed seeds were clustered around projected overshoot of roughly `187..258m`

That separated the success/failure sets much better than the earlier recoverability-buffer trigger, which either armed too late or armed the wrong seeds.

### What worked

- backstop-only focused bundle improved from `4/10` to `10/10`
- the bad seeds now enter `terrain_divert`, while the already-good seeds stay on `latest_safe`
- the normal quick pack success/crash totals stayed unchanged

### What still costs something

- the successful terrain-divert runs use a visibly stronger terminal containment maneuver
- success improved with a moderate compute increase on the normal quick pack, around `+4.7%` avg total ms/tick in the clean sequential quick compare

### Updated lesson

For `containment_backstop`, the useful decomposition is:

- gate on projected corridor overshoot
- use a dedicated terminal containment mode once armed

The earlier "small terrain bias beside the normal terminal controller" was not enough. The fix needed an explicit temporary behavior that prioritizes killing outward velocity while maintaining enough vertical support to stay recoverable.

Current review note:

- the resulting maneuver can still run visibly close to the wall
- that is expected under the current trigger, because it is protecting corridor recoverability rather than maximizing geometric wall clearance
- so wall proximity alone is not the main failure signal for this pass
- the more important remaining quality question is whether the containment arc still reads as acceptably reactive instead of a new route class

## Prototype findings: setup-time terrain summaries

The next refinement kept the same containment idea but changed the arming architecture:

- move target-side terrain discovery into setup-time environment construction
- precompute target ground height plus first elevated boundary on each side of target
- replace hot-path terrain sampling with an O(1) corridor-overshoot check at runtime

This confirmed the architectural split:

- generic terrain-derived summaries are a good fit for detection/arming
- `containment_backstop` can still use the same terminal containment response
- `clip` and `follow` remain separate control problems and were not improved by this pass

Current status of that summary-based version:

- `terrain:flat:far:backstop:half` stayed `10/10`
- normal quick-pack behavior returned to exact parity with the baseline
- compute improved substantially relative to the earlier trajectory-sampling probe, but still regressed on the normal quick pack enough to need another optimization pass

## Prototype findings: barrier-shape prefilter

The missing optimization was not more sampling. It was a better generic definition of when target-side terrain should count as a lateral containment hazard at all.

The false positives came from uphill target pads:

- the first summary-based pass treated any elevated terrain beyond target as a possible backstop
- steep `climb:*` target pads therefore armed `lateral_containment` even though they were just normal rising terrain
- that kept the quick normal pack behavior-correct, but still added hot-path cost

The useful generic shape test was:

- a containment boundary must have a steep initial rise
- and that rise must flatten shortly afterward

That distinguishes:

- `backstop`: steep edge followed by a flat or nearly flat tail
- ordinary climb terrain: steep-ish edge that keeps rising afterward

Implementation shape:

1. At setup time, precompute for each target-side boundary:
   - initial `steepness`
   - `tail_steepness` over the next equal-width window
2. In the runtime prefilter:
   - exit immediately if neither side qualifies as a barrier-shaped containment boundary
   - only then evaluate overshoot / outward-velocity arming

Measured outcome:

- `terrain:flat:far:backstop:half` stayed `10/10`
- normal quick-pack terrain probes dropped back to `0` outside the actual backstop case
- quick normal-pack compute returned to near-parity with baseline, about `+0.9%` avg total ms/tick

Current practical lesson:

- for `containment_backstop`, the big win is a strong setup-time geometric prefilter
- the expensive part should not be "sampling smarter every tick"
- it should be "classify which target-side terrain even deserves containment logic, once"

## Sources

- ZEM/ZEV guidance: Zhang et al., "Collision Avoidance ZEM/ZEV Guidance for Mars" (Acta Astronautica, 2017)
- Two-phase terrain guidance: Guo et al., "Two-Phase ZEM/ZEV Guidance for Mars Landing" (AIAA J. Guidance, 2020)
- G-FOLD: Acikmese & Ploen, "Convex Programming Approach to Powered Descent Guidance for Mars Landing" (J. Guidance, 2007)
- Lossless convexification: Blackmore et al., larsblackmore.com/losslessconvexification.htm
- Controllable sets for lunar landing: MERL TR2024-004, "Lunar Landing with Feasible Divert using Controllable Sets"
- ALHAT: NASA Autonomous Landing Hazard Avoidance Technology program
- Divert capability / reachable sets: arXiv 2305.13846, "Descent & Landing with Divert for Moon Landing"
