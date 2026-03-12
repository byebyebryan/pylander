# Setup Tuning Notes

Checkpoint for the dedicated PDG setup controller after the `pdx`-first shaping rebuild.

## Current behavior

- Setup is now geometry-first instead of apex-band-first.
- The setup objective is:
  - pathwise `projected_dx` reduction over the active handoff window
  - one-sided target-y support, with a weaker excess-loft penalty instead of a symmetric crossing target
  - one-sided angle shortfall shaping, active only when the live post-cut entry is shallower than `setup_descent_angle_deg_target`
- Setup thrust may not point away from the actual target direction while setup is still outside the `dx` corridor.
- Future projected miss is constrained to stay on the target side during setup planning.
- Setup pass latching is settle-aware again: the controller cuts when the short settle window still projects a valid setup gate.
- Setup reference times are now live-state based for every setup case; the old plan-terminal proxy was removed.

## Current setup-goal status

Last checked with:

```bash
uv run python main.py sim <selector> --bot pdg --freq 0 -t 25
```

| Selector | Verdict | Notes |
| --- | --- | --- |
| `setup_flat:near:setup:0` | `pass` | `projected_dx=51.06`, `angle=51.66`, `alt=37.70` |
| `setup_flat:mid:setup:0` | `angle` | `projected_dx=-53.57`, `angle=33.80`, `alt=67.10` |
| `setup_flat:far:setup:0` | `dx` | `projected_dx=-94.01`, `angle=41.13`, `alt=113.90` |
| `setup_downhill:low:setup:0` | `pass` | `projected_dx=50.01`, `angle=64.51`, `alt=41.62` |
| `setup_downhill:mid:setup:0` | `pass` | `projected_dx=47.24`, `angle=71.72`, `alt=30.63` |
| `setup_downhill:high:setup:0` | `pass` | `projected_dx=49.71`, `angle=79.97`, `alt=31.38` |
| `setup_climb:low:setup:0` | `pass` | `projected_dx=51.61`, `angle=52.09`, `alt=113.27` |
| `setup_climb:mid:setup:0` | `pass` | `projected_dx=-7.81`, `angle=45.26`, `alt=155.38` |
| `setup_climb:high:setup:0` | `pass` | `projected_dx=-41.23`, `angle=46.95`, `alt=96.15` |

Summary:

- Working: `7/9`
- Remaining failures: `setup_flat:mid`, `setup_flat:far`

## What improved

- The previous flat pathology is gone:
  - no setup x-thrust away from the target direction
  - no abrupt high-apex climb caused by symmetric setup shaping
- Downhill stays solved under the rebuilt objective.
- Climb-low and climb-high both moved from failure to pass under the geometry-first gate.
- End-to-end smokes stay healthy:
  - `setup_flat:near:0` landed in `16.60s`, offset `10.74`
  - `setup_downhill:mid:0` landed in `22.80s`, offset `5.51`
  - `setup_climb:mid:0` landed in `27.57s`, offset `0.10`
  - `flare_normal:mid:0`, `flare_error:mid_wide:0`, and `plunge:mid_normal:0` all still land

## What is still not working

- `setup_flat:mid` still cuts into a shallow overshoot:
  - `projected_dx=-53.57`
  - `angle=33.80`
- `setup_flat:far` still overshoots harder and is also shallow:
  - `projected_dx=-94.01`
  - `angle=41.13`

These are now clearly the same remaining problem:

- the rebuilt objective fixed the wrong-direction thrust and the runaway climb
- the remaining flat gap is a large-distance shallow-overshoot case
- the next pass should focus on reducing cutoff horizontal speed in long flat transfers without reopening the old downhill/climb regressions

## Key design changes from the reverted pass

- Apex is no longer a setup pass/fail target.
- Setup quality now gates on:
  - target-y reachability
  - projected `dx`
  - minimum descent angle
- The setup controller no longer fails reachable setup just because the planner briefly tapers thrust.
- Overshoot handling is geometry-based instead of scenario-based:
  - no-away thrust is tied to actual target direction
  - future projected miss is kept on the target side inside the optimizer

## Useful commands

Focused setup-goal sweep:

```bash
uv run python main.py sim setup_flat:near:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_flat:mid:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_flat:far:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_downhill:low:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_downhill:mid:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_downhill:high:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_climb:low:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_climb:mid:setup:0 --bot pdg --freq 0 -t 25
uv run python main.py sim setup_climb:high:setup:0 --bot pdg --freq 0 -t 25
```

Plot pack:

```bash
uv run python main.py plot <selector> --bot pdg --freq 0 -t 25 -p all -o both
```

Shared-stack smoke:

```bash
uv run python main.py sim setup_flat:near:0 --bot pdg --freq 0 -t 45
uv run python main.py sim setup_downhill:mid:0 --bot pdg --freq 0 -t 45
uv run python main.py sim setup_climb:mid:0 --bot pdg --freq 0 -t 45
uv run python main.py sim flare_normal:mid:0 --bot pdg --freq 0 -t 20
uv run python main.py sim flare_error:mid_wide:0 --bot pdg --freq 0 -t 20
uv run python main.py sim plunge:mid_normal:0 --bot pdg --freq 0 -t 20
```
