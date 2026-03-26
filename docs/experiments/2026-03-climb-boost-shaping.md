# Climb boost shaping experiment (March 2026)

> Legacy experiment note. The work predates the public `setup/flare` ->
> `boost/terminal` rename and the later boost cargo tiers. The prose and command
> examples below use current public terminology; quoted artifact filenames and
> commit subjects are retained verbatim when they refer to historical outputs.

## Scope and goal

This experiment focused on `pdg` boost-phase behavior for `climb`, with a narrow objective:

- get boost onto a ballistic path centered on target (`projected_dx ~= 0`),
- hit a usable apex margin above target (treated as roughly +100 during tuning),
- keep boost-cutoff behavior tied to burn end (no boost-cutoff logic rewrite).

The work intentionally biased toward climb boost behavior first, then checked broad regressions.

## What was extracted to `main` (safe/QoL)

These commits are already on `main`:

1. `9cd0ef2` `refactor: add reusable ballistic apex helpers`
- added shared ballistic helpers in `bots/common_ballistics.py` (`ballistic_apex_from_state`, analytic target-y crossing projection, apex fallback signaling).

2. `30187dc` `feat: add setup gate apex telemetry fields`
- added boost-cutoff telemetry for projected apex (`zem_boost_cutoff_projected_apex_y`, `zem_boost_cutoff_projected_apex_over_target`) and wired through eval snapshots/results.

3. `d73d6b6` `refactor: switch zem projection to terrainless analytic path`
- switched ZEM projection usage to analytic terrainless target-y crossing/fallback path and updated tests.

## Experimental changes still under tuning

Historical touched files in the current layout:

- `bots/pdg_optimizer.py`
- `bots/pdg_planner.py`
- `bots/pdg_actuation.py`
- `bots/pdg_tracking.py`
- `bots/pdg_config.py`
- `bots/pdg.py`
- `levels/climb.py`

Main themes:

- boost optimizer objective reshaped around projected-dx + apex goals,
- explicit boost-goal slacks and tolerances (`projected_dx`, `apex_y`, `apex_vy`),
- boost burn continuity/taper adjustments to reduce early near-zero thrust,
- phase gating conditioned on `has_target_y_solution` to avoid invalid ballistic assumptions,
- climb boost path shaping via apex profile blending and adaptive apex offset/tolerance,
- climb eval snapshot capture kept alive after boost phase completion.

## What worked

1. Projection/apex diagnostics became actionable
- apex-over-target is now measured directly at boost cutoff.
- invalid target-y projection cases are explicitly flagged (`has_target_y_solution=False`) instead of silently collapsing to misleading values.

2. Climb boost quality improved for `mid`/`high`
- boost cutoff now fires with substantially better projected centerline/apex behavior than the initial pass.

## What did not work

1. `low` is still unstable end-to-end
- boost cutoff can pass, but downstream still crashes.

2. Boost-focused tuning regresses broad coverage
- non-climb scenarios (especially `coast`/`boost`/`terminal` subsets) remain heavily impacted.

3. Apex and lateral objectives still fight in edge cases
- boost can satisfy one objective while leaving a large miss on the other, especially with constrained tilt/thrust shaping.

## Measured results

### Climb focused boost-cutoff check (`boost` goal, seed `0`)

Command pattern:

```bash
uv run python main.py sim boost:climb:<scenario>:half:boost_cutoff:0 --bot pdg --freq 0
```

| Scenario | Boost cutoff time (s) | Boost cutoff projected dx | Boost cutoff apex over target |
|---|---:|---:|---:|
| `low` | 8.17 | 49.41 | 80.91 |
| `mid` | 4.83 | 19.35 | 54.36 |
| `high` | 12.67 | -6.97 | 92.02 |

### Climb end-to-end check (`landing` goal, seed `0`)

Command pattern:

```bash
uv run python main.py sim boost_climb:<scenario>:0 --bot pdg --freq 0
```

| Scenario | Final state | Fuel consumed | Notes |
|---|---|---:|---|
| `low` | `crashed` | 32.07 | boost cutoff reached, terminal entry not reached |
| `mid` | `landed` | 38.97 | terminal entry reached |
| `high` | `landed` | 52.33 | terminal entry reached |

### Broad regression signal (quick pack)

Command used:

```bash
uv run python .agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py \
  --mode quick \
  --baseline-ref main \
  --bot pdg
```

Candidate output:

- `outputs/benchmarks/d73d6b6-dirty-37fe4d21a0/quick_climb-coast-flare-etc_n16_4620ba07f3.json`
- success: `43/80` (`53.75%`)
- crashes: `37`

Worst quick-pack scenarios in current candidate (0% success in this run):

- `boost_climb:low_half`
- `coast:mid_wide`
- `coast:steep_wide`
- `terminal:shallow`
- `boost:mid_far`
- `boost:shallow_near`

Historical full-pack compare from this experiment line also showed large global regression:

- `outputs/benchmarks/16b61c8-dirty-797cab3163/full_climb-coast-flare-etc_n40_4669cfcbc0.compare_vs_16b61c8_853ad0b0.json`
- success rate `1.0 -> 0.5243`
- crashes `0 -> 176`

## Takeaway

The instrumentation and ballistic projection cleanup are clear wins and were extracted. The boost objective retuning improved climb boost behavior in some slope profiles, but broad robustness regressed significantly. The remaining tuning should stay isolated on an experiment branch until non-climb regressions are addressed.
