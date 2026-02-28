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
- Tilt cone: `|ax| <= tan(max_tilt) * ay`.
- Soft terrain guard: `y >= target_y - 8`.

These are all convex constraints, so the problem stays in QP/SOCP form and solves robustly with warm start.

### Objective terms

The cost mixes terminal accuracy, smoothness, and progress:

- Terminal error:
  - `w_terminal_x * (x_N - target_x)^2`
  - `w_terminal_y * (y_N - target_y)^2`
  - `w_terminal_vx * vx_N^2`
  - `w_terminal_vy * (vy_N - target_vy)^2`
- Control shaping:
  - effort (`ax, ay` norm-squared)
  - smoothness (`delta ax, delta ay`)
- Path shaping to linear references (`x_ref`, `y_ref`).
- Penalties for:
  - upward motion during descent,
  - dropping below descent-floor schedule,
  - asking below minimum-throttle-equivalent acceleration.
- Progress bias terms to avoid hovery local minima.

Current core MPC settings are in [`PDGOptimizerConfig`](../bots/_optimizer_pdg.py):

- horizon: `28` steps
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

This keeps a generalizable “descend fast when margin exists, brake decisively late” behavior without scenario-specific phase heuristics.

## Runtime loop

Each frame:

1. Replan at fixed rate (`replan_hz`) or on state-deviation triggers.
2. Track the current plan sample between replans.
3. Convert planned acceleration to thrust + angle with tilt/rate limits.
4. Use optimizer fallback only if solve is infeasible/error.
5. Apply touchdown hard-cut when very low, very slow, and over-pad.

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
| Time mean (s) | 20.95 | 16.51 |
| Fuel mean | 24.63 | 36.88 |
| Landing offset mean | 4.19 | 18.30 |

Per-scenario mean time (s):

| Scenario | flare | zem_zev |
| --- | --- | --- |
| shallower | 22.52 | 17.23 |
| shallow | 19.33 | 16.27 |
| mid | 19.80 | 15.99 |
| steep | 21.24 | 16.51 |
| steeper | 21.86 | 16.57 |

Interpretation:

- `zem_zev` is currently much faster to touchdown across all flare scenarios.
- `flare` remains notably better on fuel and touchdown centering.
- If objective priority is decisive high-energy descent timing, `zem_zev` currently wins.
- If objective priority is precision economy, `flare` still leads.

## Compute cost and batch throughput

The optimizer increases per-run compute, but batch parallelism amortizes it well.

Same 100-run workload (`flare` scenarios above, bot=`zem_zev`):

- `--batch-workers 1`: `127.54s`
- `--batch-workers 8`: `23.27s`
- Speedup: about `5.5x`

## Practical tuning order

1. Braking-envelope schedule (`braking_*`, `vy_*cap*`) for aggressiveness/safety.
2. Horizon/discretization (`horizon_steps`, `step_dt`) for responsiveness vs compute.
3. Terminal weights (`w_terminal_*`) for offset vs speed tradeoff.
4. Descent-floor and progress weights (`w_descent_floor`, `w_downspeed_progress`) for hover avoidance.
5. Replan thresholds (`replan_*_error`) for stability vs adaptation.
