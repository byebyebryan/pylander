---
name: pylander-benchmark-runner
description: Run reproducible Pylander benchmark packs using selector syntax (smoke, quick, full, focused), with optional baseline-vs-candidate comparison and concise regression summaries.
---

# Pylander Benchmark Runner

Use this skill when the user asks to run benchmarks, compare a change against a baseline, or check regressions after bot/controller tuning.

## Inputs

- `mode`: `smoke | quick | full | focused`
- `bot` (default: `pdg`)
- `bot_config_path` (optional JSON override path; forwarded as `--bot-config`)
- `seed_spec` (optional override, e.g. `0-9`)
- `selectors` (focused mode)
- `exclude_levels` (optional CSV/repeated level names)
- `observe_only_levels` (optional CSV/repeated level names)
- `compare_against` (optional: `main` or commit hash)

## Selector model

Benchmark command:

`uv run python main.py bench <selector ...> --bot <bot> --json auto --csv auto`

Selector format:

- `level`
- `level:layer[:... ]`
- `level:layer[:... ]:goal:seed_spec`

Goal is optional and defaults to `landing`. `seed_spec` supports ranges and CSV:
`0-9`, `0,2,4`, `3-1`.

Selector rules:

- omitted layers resolve through defaults
- `*` expands exactly one selector layer
- wildcard expansion is for `bench` / selector-pack workflows only
- canonical examples:
  - `boost:flat:far:half`
  - `terminal:error:mid:wide`
  - `plunge:mid:half`

## Mode behavior

- Source of truth: registry-backed public level benchmark metadata (`policy`, `smoke`, `quick`, `full`).
- Profile validation is strict (fail-fast) for invalid/incomplete scenario sets.

- `smoke`
  - Very fast sanity run.
  - Uses each included level profile's `smoke` scenarios.
  - Default seeds: `0-1`.

- `quick`
  - Regression guard rail with meaningful but moderate coverage.
  - Uses each included level profile's `quick` scenarios.
  - Default seeds: `0-4`.

- `full`
  - Comprehensive suite.
  - Uses each included level profile's `full` scenarios.
  - Default seeds: `0-9`.

- `focused`
  - Uses caller-selected scope.
  - Omitted layers still resolve through defaults.
  - Use `*` when the caller wants expansion instead of a defaulted selector.
  - Focused selectors also accept group aliases:
    - `@terminal` / `@terminal_flight` -> `terminal`
    - `@plunge` -> `plunge`
    - `@terminal_plunge` -> `terminal`, `plunge`
  - Explicit selectors always run even if a level is marked `excluded`.
  - Default seeds for unseeded selectors: `0-9`.

Policy behavior:

- `excluded`: omitted from auto packs (`smoke|quick|full`)
- `observe_only`: included in auto packs but excluded from global regression gating
- Runtime overrides:
  - `--exclude-levels ...`
  - `--observe-only-levels ...`

## Standard workflow

1. Resolve selectors from requested mode.
2. Run candidate benchmark (or reuse cache hit).
3. If comparison requested, reuse baseline cache for the same selector pack.
4. Summarize:
   - global section (normal levels only): success/crash and fuel deltas
   - observation section (observe-only/excluded runs): separate informational deltas
   - compute section (avg + p90/p99 ms/tick): total, passive, update deltas
   - primary fuel deltas using success-only aggregates by default
   - secondary all-runs fuel deltas (for context when crashes/outliers skew results)
- worst regressions by canonical selector group
   - newly introduced crashes split by global vs observation section

## Local cache model

- Cache root: `outputs/benchmarks/<commit-hash>/`
- Dirty workspaces use `outputs/benchmarks/<head>-dirty-<fingerprint>/`
- One selector-pack stem per benchmark config.
- Files per run:
  - `<stem>.json` (bench summary+records)
  - `<stem>.csv` (normalized row records)
  - `<stem>.meta.json` (mode/selectors/options)

This cache is local-machine only and should not be committed.

Baseline compare precondition:

- comparing against another ref (for example `--baseline-ref main`) requires that selector pack cache to already exist for that baseline ref on this machine.
- if baseline cache is missing, `run_cached_benchmark.py` fails fast with a message to seed the cache from that ref first.

Parallel-worker policy:

- If worker pools are unavailable, benchmarking errors immediately.
- No implicit sequential fallback is allowed.
- Benchmark runs use the default worker policy from `main.py bench`.

Bot compute profiling defaults for benchmark runs:

- enabled by default
- periodic profiling logs disabled by default
- cache key includes profiling options (`--bot-profile*`) so comparisons stay like-for-like

## Output format

Always include:

- exact command(s)
- selector list used
- aggregate summary deltas (primary success-only + secondary all-runs)
- compute deltas (avg/p90/p99 ms per tick) with notable spike callouts
- per-scenario notable regressions (`level:scenario`)
- crash regression details:
  - selector(s), failure mode, key telemetry snapshot
  - repro commands for `plot` (`--plot-output both`) and `sim`/profiled `sim`
- explicit policy context (`excluded` / `observe_only` / `normal`)
- recommendation (`keep`, `investigate`, `revert`)

## Helper script

Use `scripts/build_selector_pack.py` to generate selectors and a ready-to-run bench command.

Use `scripts/run_cached_benchmark.py` to execute benchmark packs with cache reuse and optional baseline comparison.

Examples:

- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode smoke`
- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode full --seed-spec 0-19`
- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode focused --selectors boost:flat:far:half boost`
- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode focused --selectors @terminal`
- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode quick --exclude-levels flat,mountains --observe-only-levels boost`
- `uv run python skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode quick --bot-profile --no-bot-profile-logs`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode quick --baseline-ref main`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode quick --baseline-ref main --bot-profile --no-bot-profile-logs`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors @terminal --seed-spec 0-9 --baseline-ref main`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors boost:downhill:* boost:flat:far:half --seed-spec 0-9 --baseline-ref main`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode full --baseline-ref main --exclude-levels flat,mountains --observe-only-levels boost`
- `uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors boost:flat:far:half --seed-spec 0-4 --bot-config configs/zem_tuning.json`
