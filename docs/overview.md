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
- Unified optimizer telemetry: `zem_*` gate + solver fields
- Focused stage coverage metrics:
  - `climb_phase_*`
  - `setup_phase_*`
  - `coast_phase_*`

## Where things live

- CLI + batch evaluation: [`main.py`](../main.py)
- Game loop + raw metrics: [`game.py`](../game.py)
- Bot sensor/action API contract: [`core/bot.py`](../core/bot.py)
- Metric normalization + aggregation: [`core/eval.py`](../core/eval.py)
- Scenario levels: [`levels/`](../levels/)
- Bot implementations: [`bots/`](../bots/)
- Headless trajectory plots: [`utils/plot.py`](../utils/plot.py)

## Bot API (sensor/action)

Implement `Bot.update(dt, passive, active) -> BotAction`.

`BotAction` outputs are target-based:

- `target_thrust`: `0..vehicle.max_thrust`
- `target_angle`: radians (`0` = upright)
- `refuel`: `True/False`
- `status`: short UI/log string
- `message`: optional transient text

`PassiveSensors` includes pose, terrain context, kinematics, mass/fuel/thrust state, and radar/proximity readings.

`ActiveSensors` supports:

- `raycast(...)`
- `terrain_height(...)`
- `terrain_profile(...)`
- `ballistic_trajectory(...)`

Notes:

- Bots should use the sensor/action API, not engine internals.
- `ActiveSensors` is rebuilt per bot step and caches repeated ballistic queries within the step.

## QueryBot API (batched active sensors)

For new bots, you can use the optional two-stage API:

- `plan(dt, passive) -> list[BotQuery]`
- `act(dt, passive, results) -> BotAction`

`QueryBot` runs in the game loop as:

1. build passive sensors
2. call `plan(...)`
3. evaluate requested active queries in one batch
4. call `act(...)`

Current built-in bots on this interface:

- `query_demo`
- `plunge`
- `zem_zev`

Supported queries (`core/bot_queries.py`):

- `BotQueryRaycast`
- `BotQueryTerrainProfile`
- `BotQueryBallistic`

Results are keyed by query `id` and returned as typed payloads:

- `RaycastResult`
- `TerrainProfileResult`
- `BallisticResult`

Batch evaluator behavior:

- duplicate query IDs are rejected
- ballistic requests are deduped per tick by input tuple
- cached ballistic results are cloned per query ID so bots can safely mutate local copies

Backward compatibility:

- Existing external/custom bots can keep using `Bot.update(..., active)` unchanged.
- Only bots that subclass `QueryBot` use the batched query path.

Demo implementation:

- [`bots/query_demo.py`](../bots/query_demo.py)

## Bot-loop profiling

Headless runs can emit timing breakdowns with env vars:

- `PYLANDER_BOT_PROFILE=1`
- `PYLANDER_BOT_PROFILE_INTERVAL_S=<seconds>` (default `5.0`)

Reported buckets:

- passive sensor build time
- legacy active sensor build time
- query evaluation time (query bots)
- bot update time (`update` or `plan+act`)

Final run result also includes `bot_profile_*` summary fields.
