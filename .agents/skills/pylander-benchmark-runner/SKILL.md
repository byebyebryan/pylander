---
name: pylander-benchmark-runner
description: Run reproducible Pylander benchmark packs, reuse local cache, and publish unified static benchmark reports.
---

# Pylander Benchmark Runner

Use this skill when the user asks to:

- run a benchmark pack
- compare current work against a cached baseline
- render a shareable HTML report with unified numbers and plots
- serve `outputs/` for local or remote viewing

The skill scripts are thin wrappers only. Real logic lives in reusable modules:

- `app.selector_pack`
- `app.run_cached_benchmark`
- `app.trace_bundle`
- `app.output_viewer`
- `app.serve_outputs`

Prefer these entrypoints:

- selector pack preview:
  `uv run python .agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py ...`
- cached benchmark run or baseline compare:
  `uv run python .agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py ...`
- unified report bundle:
  `uv run python .agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py ...`
- direct outputs server:
  `uv run python .agents/skills/pylander-benchmark-runner/scripts/serve_outputs.py ...`

## Inputs

- `mode`: `smoke | quick | full | focused`
- `bot`: default `pdg`
- `baseline_ref`: optional cached baseline ref such as `main`
- `seed_spec`: optional override such as `0-9`
- `selectors`: focused mode only
- `exclude_levels` / `observe_only_levels`: optional policy overrides
- `bot_config`: optional JSON override path
- `trace_detail`: default `report`

## Grounded workflow

1. Resolve selectors from benchmark metadata with `build_selector_pack.py`.
2. Run or reuse the candidate tracepack with `run_cached_benchmark.py`.
3. If `baseline_ref` is provided, require a seeded local cache for the same pack and compare like-for-like.
4. If the user wants "report", "bundle", "plots", or a URL, use `gen_bench_bundle.py`.
5. Use `serve_outputs.py` only when you need to inspect or debug the outputs server directly. The bundle command can ensure the server itself.

When the user says "quick benchmark", default to `--mode quick`.
When they say "full benchmark and plots", default to `--mode full` plus the bundle workflow.
When they ask for one scenario or a small slice, use `--mode focused --selectors ...`.

## Selector model

Selector format:

- `level`
- `level:layer[:...]`
- `level:layer[:...]:goal:seed_spec`

Selector rules:

- omitted layers resolve through defaults
- `*` expands exactly one selector layer in benchmark workflows
- goal defaults to `landing`
- seed specs support ranges or CSV such as `0-9` or `0,2,4`
- focused aliases:
  - `@terminal` / `@terminal_flight`
  - `@plunge`
  - `@terminal_plunge`

## Mode behavior

- Source of truth is registry-backed benchmark metadata.
- `smoke`: fast sanity pack, default seeds `0-1`
- `quick`: normal regression guard rail, default seeds `0-4`
- `full`: broad coverage pack, default seeds `0-9`
- `focused`: explicit selectors, default seeds `0-9` for unseeded selectors
- `excluded` levels stay out of auto packs
- `observe_only` levels stay in packs but out of global regression gating

## Local cache model

- Cache root: `outputs/benchmarks/<commit-hash>/`
- Dirty workspaces use `outputs/benchmarks/<head>-dirty-<fingerprint>/`
- One selector-pack stem per benchmark config
- Bundle rendering uses the same tracepack source data for numbers and plots
- Files:
  - `<stem>.tracepack.json`
  - `<stem>.meta.json`
  - `<stem>.tracepack/traces/*.trace.json`
  - `<stem>.tracepack/previews/*.png`

This cache is local-machine only and should not be committed.

## Output format

Always include:

- exact command
- selector list
- policy context (`normal`, `observe_only`, `excluded`)
- summary deltas for compare runs
- compute deltas when profiling is enabled
- crash details and focused repro commands when regressions exist
- local paths or viewer URL when a bundle is generated

Examples:

- `uv run python .agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode smoke`
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py --mode focused --selectors @terminal`
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode quick --baseline-ref main`
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors boost:flat:far:half --seed-spec 0-4 --bot-config configs/zem_tuning.json`
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py --mode quick --baseline-ref main`
- `uv run python .agents/skills/pylander-benchmark-runner/scripts/serve_outputs.py --port 8765`
