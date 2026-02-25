# Bot Development Strategy

This document defines the bot-development framework as a phase-oriented, divide-and-conquer pipeline.

## Why This Split

Complex landing behavior is easier to tune when each bot solves one job well and hands off cleanly.

- `plunge`: vertical terminal control sandbox (idealized, no upstream handoff required).
- `flare`: terminal 2-axis landing from near-ballistic entry.
- `coast`: pre-terminal coast correction and handoff timing to `flare`.
- `launch`: trajectory establishment and handoff to `coast`.

The main chain is:

`launch -> coast -> flare`

`plunge` is a focused control test bed, not a required chain stage.

## Phase Design

### 1) Plunge Phase (`plunge` level, `plunge` bot)

**Purpose**
- Tune vertical-only terminal burn timing and decisive touchdown control.

**Start assumptions**
- Spawn is always centered above the target (`start_x = target_x = 0`).
- No horizontal setup requirement.

**Primary outcomes to optimize**
- Correct burn trigger timing (coast end -> terminal control start).
- Low-hover, low-hesitation touchdown.
- Strong vertical speed management near target.

**Scenarios**
- 3x3 altitude x weight matrix:
  - altitude tiers: `alt_low` (100), `alt_mid` (400), `alt_high` (1600)
  - weight tiers: `weight_light` (no cargo), `weight_normal` (half cargo), `weight_heavy` (full cargo)
  - scenario naming: `<alt_tier>_<weight_tier>`
  - examples: `low_light`, `mid_normal`, `high_heavy`
- Quick benchmark subset:
  - `low_normal`, `mid_normal`, `high_normal`

**Evaluation**
- Uses normal landing outcome metrics (`state`, `landing_offset`, `fuel_consumed`, `path_efficiency`, etc.).
- Best used as a control-law and timing sandbox before generalizing to other phases.

### 2) Flare Phase (`flare` level, `flare` bot)

**Purpose**
- Tune terminal 2-axis burn behavior once the vehicle is already close to a ballistic solution.

**Start assumptions**
- Half-cargo start (`2250`) on a radius-`800` upper-arc around target center (seeded random side).
- Angle-to-horizon scenarios fix `vy=0` and solve `vx` for exact center-hit ballistic entry.

**Primary outcomes to optimize**
- Burn-start timing under diverse entry angles and speeds.
- Efficient lateral + vertical terminal convergence.
- Touchdown quality without oscillation or prolonged hover.

**Scenarios**
- `shallower` (15deg)
- `shallow` (30deg)
- `mid` (45deg)
- `steep` (60deg)
- `steeper` (75deg)
- Quick benchmark subset:
  - `shallower`, `mid`, `steeper`

**Evaluation**
- Uses normal landing outcome metrics.
- Intended to validate terminal robustness across handoff-like entry conditions.

### 3) Coast Phase (`coast` level, `coast` bot)

**Purpose**
- Monitor and correct pre-terminal coast errors.
- Decide when conditions are good enough to hand off to `flare`.

**Start assumptions**
- Vehicle is on a long-ish path that may be close to target but not perfect.
- Error direction can vary by seed on correction/stress scenarios.

**Primary outcomes to optimize**
- Detect correction need early without over-correcting.
- Reduce miss while avoiding oscillation and late aggressive control.
- Handoff at stable, flare-ready conditions.

**Scenarios**
- Base profile x error tiers:
  - `glide_short`, `glide_short_correction`
  - `glide_mid`, `glide_mid_correction`
  - `glide_long`, `glide_long_correction`, `glide_long_stress_correction`
  - `flat`, `flat_correction`, `flat_stress_correction`
- Handoff mirrors:
  - `handoff_extreme`, `handoff_extreme_fast`
- Cargo variants:
  - `glide_mid_correction_cargo_high`
  - `glide_long_correction_cargo_high`
  - `glide_long_stress_correction_cargo_high`
- Quick benchmark subset:
  - `glide_mid`, `glide_long_stress_correction`, `handoff_extreme`

**Evaluation**
- `eval_mode=focused`: ends at coast handoff (`eval_phase=coast_setup`).
- `eval_mode=full`: continues to normal run end.
- Drift-specific handoff/setup metrics are emitted:
  - `coast_handoff_*`
  - `coast_setup_*`

### 4) Launch Phase (`launch` level, `launch` bot)

**Purpose**
- Establish efficient ballistic trajectory from larger offsets.
- Hand off to `coast` in a good state with minimal waste and minimal chatter.

**Start assumptions**
- Air-start, no terrain obstacles in this benchmark phase.
- Includes short/mid and longer setup, plus reverse/stress.

**Primary outcomes to optimize**
- Fast, stable setup toward near-optimal ballistic path.
- Good fuel discipline during setup.
- Reliable and clean handoff envelope to `coast`.

**Scenarios**
- Base:
  - `air_mid`
  - `air_long`
- Stress:
  - `air_mid_reverse`
- Heavy cargo:
  - `air_long_heavy`
  - `air_mid_reverse_heavy`
- Quick benchmark subset:
  - `air_mid`, `air_long`, `air_mid_reverse`, `air_long_heavy`

**Evaluation**
- `eval_mode=focused`: ends at launch handoff (`eval_phase=launch_setup`).
- `eval_mode=full`: continues downstream.
- Transfer-specific handoff/setup metrics are emitted:
  - `launch_handoff_*`
  - `launch_setup_*`

## Phase Connections

### Handoff Contracts

- `launch -> coast`
  - Runtime handoff decision in launch bot.
  - Level captures snapshot into `launch_handoff_*`.
- `coast -> flare`
  - Runtime handoff decision in coast bot.
  - Level captures snapshot into `coast_handoff_*`.
- `flare -> touchdown`
  - Final terminal landing control (uses standard run-end metrics).
- `plunge -> touchdown`
  - Independent terminal-control benchmark path (no upstream handoff required).

## Suggested tuning workflow

1. Tune vertical burn/touchdown fundamentals in `plunge`.
2. Tune terminal 2-axis behavior in `flare`.
3. Tune pre-terminal correction and handoff quality in `coast` focused mode.
4. Tune setup trajectory formation and handoff quality in `launch` focused mode.
5. Run cross-phase quick benchmark for regression checks.

## Operational notes

- Keep seed/scenario fixed when tuning one parameter.
- Compare focused-mode metrics before/after changes.
- After phase-local gains, run cross-level quick benchmark to catch regressions.
- Land-launch/full point-to-point travel remains a deferred extension.
