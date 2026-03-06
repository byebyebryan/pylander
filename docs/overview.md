# Bot development framework

Pylander bot work is now centered on a unified in-flight controller (`zem_zev`) plus a dedicated terminal benchmark bot (`plunge`).

## Control model

- `zem_zev`: optimizer-first coupled 2-axis guidance used by default in `launch`, `setup`, `coast`, `climb`, and `flare`.
- `plunge`: terminal-only benchmark bot for vertical burn timing and touchdown behavior.

The in-flight path is a single owner with internal phases (`setup -> coast -> terminal -> touchdown`), not inter-bot runtime handoffs.

## How to iterate

- Prefer headless mode while tuning:
  - `uv run python main.py sim <level[:scenario[:seed]]>`
- Fix selector seed/scenario while tuning one change.
- Use selector-based bench packs for fast regressions.
- In benchmark mode, selectors without seed specs auto-run seeds `0-9` for randomized scenarios.

## What to measure

Core metrics from game + batch aggregation:

- Outcome: `state`, `success`, `landing_offset`
- Efficiency: `fuel_consumed`, `fuel_per_distance`, `path_efficiency`
- Timing: `time`, `time_to_first_land`
- Bot eval metadata: `bot_eval_goal`, `bot_eval_early_end`, `bot_eval_end_reason`
- Unified optimizer telemetry: `zem_*` gate + solver fields

## Where things live

- CLI + batch evaluation: [`main.py`](../main.py)
- Game loop + raw metrics: [`game.py`](../game.py)
- Runtime loop extraction: [`runtime/loop_timing.py`](../runtime/loop_timing.py), [`runtime/sensors.py`](../runtime/sensors.py), [`runtime/bot_loop.py`](../runtime/bot_loop.py)
- Level capability helpers: [`core/level_capabilities.py`](../core/level_capabilities.py)
- Bot sensor/action API contract: [`core/bot.py`](../core/bot.py)
- Metric normalization + aggregation: [`core/eval.py`](../core/eval.py)
- Scenario levels: [`levels/`](../levels/)
- Bot implementations: [`bots/`](../bots/)
- Headless trajectory plots: [`utils/plot.py`](../utils/plot.py)

## Bot API (sensor/action)

Implement `Bot.update(dt, sensors) -> BotAction`.

`BotAction` outputs are target-based:

- `target_thrust`: `0..vehicle.max_thrust`
- `target_angle`: radians (`0` = upright)
- `refuel`: `True/False`
- `status`: short UI/log string
- `message`: optional transient text

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

## Plot bundles

Headless plotting supports:

- `--plot-output combined` (single overview image)
- `--plot-output split` (multiple focused panels)
- `--plot-output both` (overview + split panels)

Image size can be capped with `--plot-max-side-px` (default `1800`) to improve reliability for automated image analysis.

When plotting is enabled, run results may include:

- `plot_paths`
- `plot_manifest_path`
- `plot_bundle_dir`
