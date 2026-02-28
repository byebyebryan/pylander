# ZEM/ZEV Optimizer Bot (`zem_zev`)

Implementation: [`bots/zem_zev.py`](../bots/zem_zev.py), [`bots/_optimizer_pdg.py`](../bots/_optimizer_pdg.py)

`zem_zev` is an optimizer-first terminal guidance bot for the `flare` level family.
It replaces the legacy phase-heavy ZEM/ZEV variant with a single receding-horizon convex solve that couples horizontal and vertical control in one plan.

## Naming

Both names appear in the wild:

- `ZEM/ZEV` (Zero-Effort-Miss / Zero-Effort-Velocity) — most common naming.
- `ZEV/ZEM` — same terms reversed.

In this repo we use `zem_zev` for consistency with bot naming.

## Guidance design

At each replan, the bot solves a finite-horizon trajectory optimization in acceleration space:

- State: `x, y, vx, vy` (with `vy` positive up).
- Controls: `ax, ay` (thrust acceleration components).
- Discrete dynamics:
  - `x[k+1] = x[k] + vx[k] * dt + 0.5 * ax[k] * dt^2`
  - `y[k+1] = y[k] + vy[k] * dt + 0.5 * (ay[k] - g) * dt^2`
  - `vx[k+1] = vx[k] + ax[k] * dt`
  - `vy[k+1] = vy[k] + (ay[k] - g) * dt`

### Constraints

- Thrust non-negativity: `ay >= 0`.
- Thrust magnitude cone: `sqrt(ax^2 + ay^2) <= a_max`.
- Nominal-thrust envelope with OD reserve slack:
  - `thrust_norm >= sqrt(ax^2 + ay^2)`
  - `thrust_norm <= a_nom + od_slack`
  - `0 <= od_slack <= (a_max - a_nom)`
- Tilt cone: `|ax| <= tan(max_tilt) * ay`.
- Soft terrain guard: `y >= target_y - 8`.

These are all convex constraints, so the problem stays in QP/SOCP form and solves robustly with warm start.

### Objective terms

The cost is fuel-first while still enforcing terminal accuracy:

- Terminal error:
  - `w_terminal_x * (x_N - target_x)^2`
  - `w_terminal_y * (y_N - target_y)^2`
  - `w_terminal_vx * vx_N^2`
  - `w_terminal_vy * (vy_N - target_vy)^2`
- Control shaping:
  - effort (`ax, ay` norm-squared)
  - smoothness (`delta ax, delta ay`)
- Path shaping to linear references (`x_ref`, `y_ref`).
- Fuel proxy:
  - linear thrust cost on `thrust_norm`.
- OD reserve penalty:
  - linear + quadratic penalties on `od_slack`.
- Penalties for:
  - upward motion during descent,
  - dropping below descent-floor schedule,
  - asking below minimum-throttle-equivalent acceleration.

Current core MPC settings are in [`PDGOptimizerConfig`](../bots/_optimizer_pdg.py):

- horizons: `28` (short) and `36` (long)
- step: `0.20 s`
- solver: `CLARABEL` (fallback `SCS`)

## Vertical speed schedule (braking envelope)

Instead of a hand-tuned phase gate, the bot derives feasible descent speed from a braking envelope:

- `v_limit(h) = sqrt(v_touch^2 + 2 * a_brake * h_eff)`
- `h_eff = max(0, altitude - margin)`
- `a_brake` uses available vertical braking authority with tilt and safety scaling.

Then:

- terminal target speed = `target_ratio * v_limit`
- descent floor speed = `floor_ratio * v_limit`
- low-altitude and touchdown caps clamp both near the ground

`zem_zev` now computes this schedule using nominal thrust authority (`a_nom`) so the
plan is nominal-first by default, with OD treated as reserve inside the optimizer.

## Runtime loop

Each frame:

1. Replan at fixed rate (`replan_hz`) or on state-deviation triggers.
2. Select long/short horizon from current altitude and estimated time-to-go.
3. Track the current plan sample between replans.
4. Convert planned acceleration to thrust + angle with tilt/rate limits.
5. Use optimizer fallback only if solve is infeasible/error.
6. Apply touchdown hard-cut when very low, very slow, and over-pad.

## Fresh comparison vs `flare` bot

Benchmark command (same for both bots):

```bash
uv run python main.py flare --headless --batch \
  --batch-scenarios shallow,shallower,mid,steep,steeper \
  --batch-seeds 0-19 --batch-workers 8 --bot <flare|zem_zev>
```

Observed results (current branch, 100 runs each):

| Metric | flare | zem_zev |
| --- | --- | --- |
| Success rate | 100% | 100% |
| Time mean (s) | 21.99 | 20.31 |
| Fuel mean | 25.87 | 21.50 |
| Landing offset mean | 3.70 | 9.06 |
| Overdrive fraction mean | 0.26 | 0.38 |

Per-scenario mean time (s):

| Scenario | flare | zem_zev |
| --- | --- | --- |
| shallower | 27.94 | 23.46 |
| shallow | 19.12 | 20.88 |
| mid | 20.14 | 19.01 |
| steep | 20.96 | 19.04 |
| steeper | 21.80 | 19.15 |

Interpretation:

- `zem_zev` now leads on fuel in this flare benchmark while keeping 100% success.
- `zem_zev` still lands less centered than `flare`.
- `zem_zev` remains somewhat faster overall, but the advantage is smaller than old OD-heavy tuning.
- Fuel-first acceptance can be enforced with: `zem_zev_fuel <= flare_fuel + 1.5`.

## Compute cost and batch throughput

The optimizer increases per-run compute, but batch parallelism amortizes it well.
For tuning loops, keep `--batch-workers` high and use reduced seed sets before full 100-run validation.

## Practical tuning order

1. Braking-envelope schedule (`braking_*`, `vy_*cap*`) for aggressiveness/safety.
2. Horizon/discretization (`horizon_steps`, `step_dt`) for responsiveness vs compute.
3. Terminal weights (`w_terminal_*`) for offset vs speed tradeoff.
4. Descent-floor and fuel weights (`w_descent_floor`, `w_thrust_linear`, `w_overdrive_*`) for fuel/robustness balance.
5. Replan thresholds (`replan_*_error`) for stability vs adaptation.
