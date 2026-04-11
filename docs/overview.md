# Bot development framework

Pylander bot work is now centered on a unified in-flight controller (`pdg`) plus a dedicated plunge benchmark bot (`plunge`).

## Control model

- `pdg`: optimizer-first coupled 2-axis guidance used by default under the `boost:*` and `terminal:*` selector roots.
- `plunge`: dedicated plunge benchmark bot for the separate `plunge` level.

Repo shorthand keeps the terminal selector root (`terminal:normal:*`, `terminal:error:*:*`) separate from the plunge benchmark (`plunge`).

The in-flight path is a single owner with internal stages (`boost -> coast -> terminal -> touchdown`), not inter-bot runtime handoffs. In `pdg`, `coast` remains passive in actuation: zero thrust, retrograde attitude hold, and low-rate terminal-gate probing until terminal ignition.

## Default Vehicle Profile

Bots should assume the stock lander starts from these default vehicle limits:

- dry mass `7200 kg`
- fuel tank `140` units at `45 kg/unit`
- max cargo `6000 kg`
- nominal thrust power `240000 N`
- throttle range `0.25 .. 1.6`
- overdrive burn multiplier `8.0`

That budget keeps the fully loaded mass at roughly `19.5 t` while shifting more
of the discretionary load into fuel, so long-haul boost runs can be range
feasible without turning overdrive into a default cruise mode.

## How to iterate

- Prefer headless mode while tuning:
  - `uv run python main.py sim <level[:layer[:...]][:goal[:seed]]>`
- Fix selector seed/scenario while tuning one change.
- Use selector-based bench packs for fast regressions.
- In benchmark mode, selectors without seed specs auto-run seeds `0-9` for randomized scenarios.
- Omitted selector layers use defaults; wildcard expansion is explicit via `*`.

## What to measure

Core metrics from game + batch aggregation:

- Outcome: `state`, `success`, `landing_offset`
- Efficiency: `fuel_consumed`, `fuel_per_distance`, `path_efficiency`
- Timing: `time`, `time_to_first_land`
- Eval metadata: `eval_goal`, `eval_early_end`, `eval_end_reason`
- Generic boost/eval telemetry: `boost_cutoff_*`, `boost_goal_*`
  - on `terminal:normal:*` / `terminal:error:*:*`, `boost_cutoff_*` is the spawn-time coast-entry snapshot
- Bot-owned diagnostics: `bot_<botname>_*` (for example `bot_pdg_*`)

## Where things live

- CLI + batch evaluation: [`main.py`](../main.py)
- Game orchestration: [`game/__main__.py`](../game/__main__.py) (imported as `game`)
- Runtime loop extraction: [`game/runtime/loop_timing.py`](../game/runtime/loop_timing.py), [`game/runtime/sensors.py`](../game/runtime/sensors.py), [`bot_framework/bot_loop.py`](../bot_framework/bot_loop.py)
- Level capability helpers: [`game/core/level_capabilities.py`](../game/core/level_capabilities.py)
- Bot sensor/action API contract: [`game/core/bot.py`](../game/core/bot.py)
- Metric normalization + aggregation: [`game/core/eval.py`](../game/core/eval.py)
- Scenario levels: [`game/levels/`](../game/levels/)
- Bot implementations: [`bot_framework/bots/`](../bot_framework/bots/) (pdg, plunge)
- Headless trajectory plots: [`tooling/plot.py`](../tooling/plot.py)

## Bot API (sensor/action)

Implement `Bot.update(dt, sensors) -> BotAction`.

`BotAction` outputs are target-based:

- `target_thrust`: `0..vehicle.max_thrust`
- `target_angle`: radians (`0` = upright)
- `refuel`: `True/False`
- `status`: short human-facing fallback string
- `message`: optional transient text

Bots can also expose structured display state through `get_display_state()` for
HUD/headless presentation, and bot-owned result telemetry through
`get_bot_telemetry()`.

`Sensors` includes pose, terrain context, kinematics, mass/fuel/thrust state, and radar/proximity readings.

Notes:

- Bots should use the sensor/action API, not engine internals.
- Terrain-impact ballistic prediction is a rendering concern, not bot planning input.

## Bot-loop profiling

Headless runs can emit timing breakdowns with env vars:

- `PYLANDER_BOT_PROFILE=1`
- `PYLANDER_BOT_PROFILE_INTERVAL_S=<seconds>` (default `5.0`)

Reported buckets:

- sensor build time
- bot update time
- total bot loop time

Final run result also includes `bot_profile_*` summary fields.

Headless output is split into:

- compact per-tick ship/bot lines for live scanning
- a sectioned final-results report with generic metrics first and bot-owned
  telemetry grouped separately

## Trace capture

Headless tracing supports:

- `--trace` / `--no-trace` for single-run `run` / `sim`
- `plot` command defaults to trace capture
- `--trace-sample-period-s <seconds>` to control sampled snapshot cadence
- `--trace-detail <report|replay|debug>` to control trace verbosity

Trace detail defaults:

- `bench`: `report`
- `plot`: `debug`
- `run` / `sim` with trace enabled: `report`

Benchmark runs write canonical tracepack manifests plus per-run trace files and
preview PNGs by default. Trace-enabled run results may include:

- `trace_path`
- `trace_rel_path`
- `trace_preview_path`
- `trace_preview_rel_path`
- `run_key`
- `run_instance_id`
- `trace_detail`
- `trace_sample_period_s`
- `trace_snapshot_count`
- `trace_event_count`
- `trace_control_log_count`
