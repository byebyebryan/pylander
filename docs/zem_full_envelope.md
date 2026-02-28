# Unified ZEM/ZEV Full-Envelope Integration

This doc tracks how `zem_zev` is integrated into the full in-flight envelope.

## Current ownership model

- `flare` level default bot: `zem_zev`
- `coast` level default bot: `zem_zev`
- `launch` level default bot: `zem_zev`
- `ferry` remains a wrapper bot and hands off to `zem_zev` after pad clear

Legacy phase bots remain available:

- `launch` (legacy handoff setup)
- `coast` (legacy single-burn correction + flare handoff)
- `flare` (legacy terminal controller)

## Unified phase semantics

`zem_zev` runs one controller with internal phase labels:

- `setup`
- `coast`
- `terminal`
- `touchdown`

The bot exposes two eval gates:

- setup gate: early transfer-quality condition (`launch` focused boundary)
- terminal gate: late burn-ready condition (`coast` focused boundary)

## Evaluation schema

Canonical unified fields:

- `zem_setup_gate_done`
- `zem_setup_gate_time`
- `zem_setup_gate_altitude`
- `zem_setup_gate_projected_dx`
- `zem_terminal_gate_done`
- `zem_terminal_gate_time`
- `zem_terminal_gate_altitude`
- `zem_terminal_gate_projected_dx`
- `zem_solve_count`
- `zem_solve_ms_mean`
- `zem_solve_ms_p90`
- `zem_fallback_frames`

Compatibility fields are still emitted:

- `launch_handoff_*`
- `coast_handoff_*`

## Focused eval behavior

- `launch --eval-mode focused`:
  - unified run success: `zem_setup_gate_done == True`
  - eval phase label: `zem_setup_gate`
- `coast --eval-mode focused`:
  - unified run success: `zem_terminal_gate_done == True`
  - eval phase label: `zem_terminal_gate`

Legacy focused behavior remains unchanged when using legacy bots.

## Runtime strategy

To control optimizer overhead, replanning is phase-adaptive:

- lower frequency in `setup`
- medium frequency in `coast`
- higher frequency in `terminal`
- phase-specific deviation thresholds for replan triggers

This keeps solver load lower than constant high-rate replanning while preserving terminal responsiveness.
