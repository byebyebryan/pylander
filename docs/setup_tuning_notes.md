# Setup Tuning Notes

Checkpoint for the dedicated PDG setup controller and its current setup-goal tuning state.

## Current behavior

- Setup uses a dedicated controller with its own burn / cut / settle flow instead of reusing the generic stage wrapper.
- Setup quality is metric-gated at the setup gate.
- Downhill steep entry is allowed as long as the transfer is descending, has a target-y solution, and is not shallow.
- Uphill setup uses live-state crossing references.
- Flat and downhill setup use plan-terminal crossing references.

## Current setup-goal status

Last checked with:

```bash
uv run python main.py sim <selector> --bot pdg --freq 0 -t 25
```

| Selector | Verdict | Notes |
| --- | --- | --- |
| `setup_flat:near:setup:0` | `dx` | `projected_dx=131.13`, `angle=55.88` |
| `setup_flat:mid:setup:0` | `angle` | `projected_dx=-6.15`, `angle=34.98` |
| `setup_flat:far:setup:0` | `dx` | `projected_dx=-206.10`, `angle=29.88` |
| `setup_downhill:low:setup:0` | `pass` | `projected_dx=11.60`, `angle=61.88` |
| `setup_downhill:mid:setup:0` | `pass` | `projected_dx=-3.10`, `angle=69.86` |
| `setup_downhill:high:setup:0` | `pass` | `projected_dx=8.94`, `angle=78.42` |
| `setup_climb:low:setup:0` | `dx` | `projected_dx=178.08`, `angle=69.41` |
| `setup_climb:mid:setup:0` | `pass` | `projected_dx=-0.05`, `angle=63.01` |
| `setup_climb:high:setup:0` | `apex` | `projected_dx=-51.76`, `apex_over_target=30.60` |

Summary:

- Working: all three downhill cases, `setup_climb:mid`
- Not working: all three flat cases, `setup_climb:low`, `setup_climb:high`

## What is working

- The downhill apex target fix was important. Using the frozen transfer height delta made the downhill cases solvable.
- Relaxing the upper impact-angle limit for descending transfers was correct. Steep downhill entries like `78 deg` should not hard-fail setup.
- The uphill-specific live-state crossing reference helped climb cases more than flat/downhill.
- The dedicated setup burn / cut / settle path is structurally working and is DPP-safe.

## What is not working

- Flat setup still has poor lateral closure:
  - near stops short
  - far overshoots badly
  - mid is almost centered but still too shallow
- Climb setup still under-builds the ballistic arc at the edges:
  - low is still too far short laterally
  - high still under-builds apex and slightly overshoots dx

## Failed experiments

These were tried and then reverted because they made the pack worse overall:

- Extending setup burns for same-sign `dx` failures:
  - caused runaway vertical buildup and much worse flat / climb-low outcomes
- Using live-state crossing references for every setup case:
  - helped uphill
  - hurt downhill badly, especially `setup_downhill:high`
- Lowering `launch_takeoff_clear_altitude` from `10` to `5`:
  - made flat and downhill regress sharply
- Flat-only setup tilt schedule:
  - did not improve flat near/far
  - added noise without fixing the miss pattern
- Global distance-scaled setup cut / thrust-floor thresholds:
  - helped some uphill cases
  - hurt flat cases
  - final code keeps the uphill-only part

## Things to remember before the next pass

- Do not re-tighten downhill steep-angle gating unless there is a separate reason tied to flare feasibility. For descending transfers, steep is not a setup invalidation.
- The flat problem looks different from the uphill problem:
  - flat near needs more lateral closure without triggering runaway vertical burn
  - flat far needs less shallow overshoot
- The current flat failures look more like a cut / crossing-policy issue than an apex-target issue.
- The current climb-high failure is no longer an angle problem. It is an under-built apex problem.

## Likely next steps

1. Treat flat setup as its own tuning path instead of sharing the same setup cut / crossing behavior as downhill.
2. Revisit the flat setup cutoff logic around low-thrust taper versus forced floor.
3. For climb-high, focus on apex buildup without reintroducing the old no-target-y failure mode.
4. Keep using setup-goal runs first; only switch to full landing runs after setup metrics improve.

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
uv run python main.py sim flare_normal:mid:0 --bot pdg --freq 0 -t 20
```
