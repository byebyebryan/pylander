# Climb setup shaping experiment (March 2026)

## Scope and goal

This experiment focused on `pdg` setup-phase behavior for `climb`, with a narrow objective:

- get setup onto a ballistic path centered on target (`projected_dx ~= 0`),
- hit a usable apex margin above target (treated as roughly +100 during tuning),
- keep setup-gate behavior tied to burn end (no setup-gate logic rewrite).

The work intentionally biased toward climb setup behavior first, then checked broad regressions.

## What was extracted to `main` (safe/QoL)

These commits are already on `main`:

1. `9cd0ef2` `refactor: add reusable ballistic apex helpers`
- added shared ballistic helpers in `bots/_ballistics.py` (`ballistic_apex_from_state`, analytic target-y crossing projection, apex fallback signaling).

2. `30187dc` `feat: add setup gate apex telemetry fields`
- added setup-gate telemetry for projected apex (`zem_setup_gate_projected_apex_y`, `zem_setup_gate_projected_apex_over_target`) and wired through eval snapshots/results.

3. `d73d6b6` `refactor: switch zem projection to terrainless analytic path`
- switched ZEM projection usage to analytic terrainless target-y crossing/fallback path and updated tests.

## Experimental changes still under tuning

Current uncommitted experiment files:

- `bots/_optimizer_pdg.py`
- `bots/pdg/planner.py`
- `bots/pdg/actuation.py`
- `bots/pdg/tracking.py`
- `bots/pdg/config.py`
- `bots/pdg/__init__.py`
- `levels/climb.py`

Main themes:

- setup optimizer objective reshaped around projected-dx + apex goals,
- explicit setup-goal slacks and tolerances (`projected_dx`, `apex_y`, `apex_vy`),
- setup burn continuity/taper adjustments to reduce early near-zero thrust,
- phase gating conditioned on `has_target_y_solution` to avoid invalid ballistic assumptions,
- climb setup path shaping via apex profile blending and adaptive apex offset/tolerance,
- climb eval snapshot capture kept alive after setup phase completion.

## What worked

1. Projection/apex diagnostics became actionable
- apex-over-target is now measured directly at setup gate.
- invalid target-y projection cases are explicitly flagged (`has_target_y_solution=False`) instead of silently collapsing to misleading values.

2. Climb setup quality improved for `slope_mid`/`slope_high`
- setup gate now fires with substantially better projected centerline/apex behavior than the initial pass.

## What did not work

1. `slope_low` is still unstable end-to-end
- setup gate can pass, but downstream still crashes.

2. Setup-focused tuning regresses broad coverage
- non-climb scenarios (especially `coast`/`setup`/`flare` subsets) remain heavily impacted.

3. Apex and lateral objectives still fight in edge cases
- setup can satisfy one objective while leaving a large miss on the other, especially with constrained tilt/thrust shaping.

## Measured results

### Climb focused setup-gate check (`--eval-mode focused`, seed `0`)

Command pattern:

```bash
uv run python main.py sim climb:<scenario>:0 --bot pdg --freq 0 --eval-mode focused
```

| Scenario | Setup gate time (s) | Setup gate projected dx | Setup gate apex over target |
|---|---:|---:|---:|
| `slope_low` | 8.17 | 49.41 | 80.91 |
| `slope_mid` | 4.83 | 19.35 | 54.36 |
| `slope_high` | 12.67 | -6.97 | 92.02 |

### Climb end-to-end check (`--eval-mode full`, seed `0`)

Command pattern:

```bash
uv run python main.py sim climb:<scenario>:0 --bot pdg --freq 0 --eval-mode full
```

| Scenario | Final state | Fuel consumed | Notes |
|---|---|---:|---|
| `slope_low` | `crashed` | 32.07 | setup gate reached, flare entry not reached |
| `slope_mid` | `landed` | 38.97 | flare entry reached |
| `slope_high` | `landed` | 52.33 | flare entry reached |

### Broad regression signal (quick pack)

Command used:

```bash
uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py \
  --mode quick \
  --baseline-ref main \
  --bot pdg
```

Candidate output:

- `outputs/benchmarks/d73d6b6-dirty-37fe4d21a0/quick_climb-coast-flare-etc_n16_4620ba07f3.json`
- success: `43/80` (`53.75%`)
- crashes: `37`

Worst quick-pack scenarios in current candidate (0% success in this run):

- `climb:slope_low`
- `coast:mid_wide`
- `coast:steep_wide`
- `flare:shallow`
- `setup:mid_far`
- `setup:shallow_near`

Historical full-pack compare from this experiment line also showed large global regression:

- `outputs/benchmarks/16b61c8-dirty-797cab3163/full_climb-coast-flare-etc_n40_4669cfcbc0.compare_vs_16b61c8_853ad0b0.json`
- success rate `1.0 -> 0.5243`
- crashes `0 -> 176`

## Takeaway

The instrumentation and ballistic projection cleanup are clear wins and were extracted. The setup objective retuning improved climb setup behavior in some slope profiles, but broad robustness regressed significantly. The remaining tuning should stay isolated on an experiment branch until non-climb regressions are addressed.
