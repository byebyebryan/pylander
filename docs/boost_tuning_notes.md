# Boost Tuning Notes

Checkpoint for the dedicated PDG boost controller after the `pdx`-first shaping rebuild.

> Note: this note predates the `empty/half/full` cargo split and the public
> `setup/flare` -> `boost/terminal` rename. The commands below use current
> public selectors and goal names while preserving the historical findings.

## Current behavior

- Boost is now geometry-first instead of apex-band-first.
- The boost objective is:
  - pathwise `projected_dx` reduction over the active handoff window
  - one-sided target-y support, with a weaker excess-loft penalty instead of a symmetric crossing target
  - one-sided angle shortfall shaping, active only when the live post-cut entry is shallower than `boost_descent_angle_deg_target`
- Boost thrust may not point away from the actual target direction while boost is still outside the `dx` corridor.
- Future projected miss is constrained to stay on the target side during boost planning.
- Boost cut remains settle-aware, but boost-cutoff telemetry now waits for actual thrust to decay to idle so the recorded handoff state is truly ballistic.
- Boost reference times are now live-state based for every boost case; the old plan-terminal proxy was removed.
- Terminal now uses a recoverability-based dynamic tilt cap:
  - lateral authority can relax beyond the base terminal tilt envelope only when the current state can still brake vertically after that side-burn
  - gate, planner, and actuation all consult the same helper so the terminal stack stays consistent

## Current boost-goal status

Last checked with:

```bash
uv run python main.py sim <selector> --bot pdg --freq 0 -t 25
```

| Selector | Verdict | Notes |
| --- | --- | --- |
| `boost_flat:near_half:boost:0` | `pass` | `projected_dx=51.06`, `angle=51.66`, `alt=37.70` |
| `boost_flat:mid_half:boost:0` | `angle` | `projected_dx=-53.57`, `angle=33.80`, `alt=67.10` |
| `boost_flat:far_half:boost:0` | `dx` | `projected_dx=-94.01`, `angle=41.13`, `alt=113.90` |
| `boost_downhill:low_half:boost:0` | `pass` | `projected_dx=50.01`, `angle=64.51`, `alt=41.62` |
| `boost_downhill:mid_half:boost:0` | `pass` | `projected_dx=47.24`, `angle=71.72`, `alt=30.63` |
| `boost_downhill:high_half:boost:0` | `pass` | `projected_dx=49.71`, `angle=79.97`, `alt=31.38` |
| `boost_climb:low_half:boost:0` | `pass` | `projected_dx=51.61`, `angle=52.09`, `alt=113.27` |
| `boost_climb:mid_half:boost:0` | `pass` | `projected_dx=-7.81`, `angle=45.26`, `alt=155.38` |
| `boost_climb:high_half:boost:0` | `pass` | `projected_dx=-41.23`, `angle=46.95`, `alt=96.15` |

Summary:

- Working: `7/9`
- Remaining failures: `boost_flat:mid_half`, `boost_flat:far_half`

## What improved

- The previous flat pathology is gone:
  - no boost x-thrust away from the target direction
  - no abrupt high-apex climb caused by symmetric boost shaping
- Downhill stays solved under the rebuilt objective.
- Climb-low and climb-high both moved from failure to pass under the geometry-first gate.
- End-to-end smokes stay healthy:
  - `boost_flat:near_half:0` landed in `16.60s`, offset `10.74`
  - `boost_downhill:mid_half:0` landed in `22.80s`, offset `5.51`
  - `boost_climb:mid_half:0` landed in `27.57s`, offset `0.10`
  - `terminal_normal:mid:0`, `terminal_error:mid_wide:0`, and `plunge:mid_normal:0` all still land

## What is still not working

- `boost_flat:mid_half` still cuts into a shallow overshoot:
  - `projected_dx=-53.57`
  - `angle=33.80`
- `boost_flat:far_half` still overshoots harder and is also shallow:
  - `projected_dx=-94.01`
  - `angle=41.13`

These are now clearly the same remaining problem:

- the rebuilt objective fixed the wrong-direction thrust and the runaway climb
- the remaining flat gap is a large-distance shallow-overshoot case
- the next pass should focus on reducing cutoff horizontal speed in long flat transfers without reopening the old downhill/climb regressions

## Terminal follow-up after the boost-cutoff fix

After the boost-cutoff correction, the remaining bad full-flight behavior on
`boost_flat:mid_half` / `boost_flat:far_half` was mostly terminal-side, not boost-side:

- boost handoff geometry was imperfect but recoverable
- terminal was already trying to use as much lateral authority as the old terminal
  tilt cap allowed
- the fixed terminal tilt cap was too conservative for the hot flat recoveries

The current terminal change keeps the one-engine thrust coupling but relaxes terminal
tilt dynamically from recoverability instead of a hard altitude rule:

- if a more sideways terminal burn would still leave a vertically recoverable state,
  terminal may use more tilt
- if the state is vertically tight, terminal falls back to the old base terminal tilt

Quick regression result from the current dynamic-tilt pass:

- focused 70-run slice (`boost_flat:{mid_half,far_half}`, `boost_downhill:mid_half`,
  `boost_climb:mid_half`, `terminal_normal:mid`, `terminal_error:mid_wide`,
  `plunge:mid_normal`, seeds `0-9`) landed `70/70`
- seed-0 flat full-flight improved materially versus the committed baseline:
  - `boost_flat:mid_half:0` offset `0.62` vs `3.40`
  - `boost_flat:far_half:0` offset `0.88` vs `4.24`
- representative terminal flights stayed healthy:
  - `terminal_normal:mid:0` still landed cleanly at offset `2.94`
  - `terminal_error:mid_wide:0` still landed at offset `15.54`

## Findings from the next attempted pass

The follow-on tuning pass was tried and then reverted because it regressed the
shared-stack `boost_flat:mid_half:0` smoke even though it improved some focused boost
metrics.

What was learned:

- A corridor-style `projected_dx` objective by itself is not enough. It still
  let the optimizer carry too much horizontal speed into long flat handoffs.
- Uniform boost-horizon weighting also was not enough. The flat failures are not
  mainly caused by tail-weighting alone.
- A kinematic crossing-time floor that accounts for current targetward `vx`
  improved the focused `boost_flat:far_half:boost:0` geometry in the right direction:
  lower fuel, less time aloft, and steeper entry than the naive zero-velocity
  floor.
- Increasing angle pressure and excess-loft pressure without a stronger
  end-to-end acceptance check can make the focused boost plots look cleaner while
  still regressing the downstream shared stack.

Working hypothesis after the reverted pass:

- The remaining flat problem is still “too much horizontal energy at handoff,”
  but not every convex proxy for that helps downstream behavior.
- The most promising source-level idea from the reverted pass was the
  kinematic crossing-time floor based on current targetward `vx`; that is worth
  revisiting, but only with end-to-end `boost_flat:mid_half:0` smoke in the inner
  loop.

## Key design changes from the reverted pass

- Apex is no longer a boost pass/fail target.
- Boost quality now gates on:
  - target-y reachability
  - projected `dx`
  - minimum descent angle
- The boost controller no longer fails reachable boost just because the planner briefly tapers thrust.
- Overshoot handling is geometry-based instead of scenario-based:
  - no-away thrust is tied to actual target direction
  - future projected miss is kept on the target side inside the optimizer

## Useful commands

Focused boost-goal sweep:

```bash
uv run python main.py sim boost_flat:near_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_flat:mid_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_flat:far_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_downhill:low_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_downhill:mid_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_downhill:high_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_climb:low_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_climb:mid_half:boost:0 --bot pdg --freq 0 -t 25
uv run python main.py sim boost_climb:high_half:boost:0 --bot pdg --freq 0 -t 25
```

Plot pack:

```bash
uv run python main.py plot <selector> --bot pdg --freq 0 -t 25 -p all -o both
```

Shared-stack smoke:

```bash
uv run python main.py sim boost_flat:near_half:0 --bot pdg --freq 0 -t 45
uv run python main.py sim boost_downhill:mid_half:0 --bot pdg --freq 0 -t 45
uv run python main.py sim boost_climb:mid_half:0 --bot pdg --freq 0 -t 45
uv run python main.py sim terminal_normal:mid:0 --bot pdg --freq 0 -t 20
uv run python main.py sim terminal_error:mid_wide:0 --bot pdg --freq 0 -t 20
uv run python main.py sim plunge:mid_normal:0 --bot pdg --freq 0 -t 20
```
