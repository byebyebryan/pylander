---
name: pylander-benchmark
description: "Run the full Pylander benchmark workflow: inspect context, infer or honor scope and baseline, reuse cache, analyze outcomes, publish reports, and promote validated dirty caches."
---

# Pylander Benchmark

Use this skill when the user asks to:

- run the bench
- run a quick, full, or focused benchmark
- compare current work against a meaningful baseline
- analyze the latest results or rerender an existing report
- serve `outputs/` or promote a validated dirty benchmark after commit

Use the unified benchmark CLI directly:

- `uv run python -m app.bench selectors ...`
- `uv run python -m app.bench inspect ...`
- `uv run python -m app.bench run ...`
- `uv run python -m app.bench analyze ...`
- `uv run python -m app.bench report ...`
- `uv run python -m app.bench bundle ...`
- `uv run python -m app.bench serve ...`
- `uv run python -m app.bench promote ...`

Implementation lives in reusable modules:

- `app.selector_pack`
- `app.benchmark_context`
- `app.run_cached_benchmark`
- `app.benchmark_analyze`
- `app.trace_bundle`
- `app.output_viewer`
- `app.serve_outputs`
- `app.benchmark_promote`
- `app.bench`

## Inputs

- `mode`: `smoke | quick | full | focused`
- `bot`: default `pdg`
- `baseline_ref`: default `auto`; explicit refs still win
- `seed_spec`: optional override such as `0-9`
- `selectors`: focused mode only
- `exclude_levels` / `observe_only_levels`: optional policy overrides
- `bot_config`: optional JSON override path
- `goal_summary` / `context_note`: optional context to record in the run intent

## Default behavior

When the user says "run the bench", use the full workflow:

1. Inspect repo state and recent first-parent history with `app.bench inspect` or the `bundle` path.
2. Decide scope conservatively:
   - explicit user scope wins
   - otherwise default to `quick`
   - use `focused` only when the request and touched code clearly point to a narrow scenario family
3. Resolve baseline:
   - explicit `--baseline-ref` wins
   - otherwise use `--baseline-ref auto`
   - auto baseline may skip docs, skills, tests, and benchmark tooling commits, but must stop at likely behavior-affecting code
   - if the chosen baseline cache is missing and the user wants a real compare, use `--missing-baseline seed`
   - default missing-baseline policy is `skip` for auto baselines and `error` for explicit baselines
   - seeded baselines assume the primary outputs are still comparable across commits; if old runtime or config changes redefine the pack or metrics, call that out
4. Record the run intent.
5. Run or reuse the candidate tracepack and baseline compare.
6. Generate the analysis sidecar.
7. Render the HTML report with context, baseline rationale, measured outcome, and likely causes.

Use `uv run python -m app.bench bundle ...` for this default path.

Use narrower commands only when the user is explicitly asking for an intermediate phase:

- `selectors`: preview the pack only
- `inspect`: gather repo facts, baseline candidates, and cache paths
- `run`: execute or reuse artifacts from explicit args or an existing intent
- `analyze`: analyze existing artifacts without rerunning benchmarks
- `report`: rerender HTML from existing artifacts
- `serve`: debug or reuse the outputs server directly
- `promote`: copy a validated dirty cache onto a clean commit key after commit

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
- Reports use the same tracepack source data for numbers and plots
- Files:
  - `<stem>.tracepack.json`
  - `<stem>.meta.json`
  - `<stem>.tracepack/traces/*.trace.json`
  - `<stem>.tracepack/previews/*.png`
  - `<stem>.tracepack.intent.json`
  - `<stem>.tracepack.analysis.json`

This cache is local-machine only and should not be committed.

## Output format

Always include:

- exact command
- inferred or explicit benchmark intent
- resolved baseline and skipped-commit rationale when using auto baseline
- summary deltas for compare runs
- verdict (`improvement | regression | mixed | no_change | investigate`)
- likely causes and concrete follow-up commands when analysis is available
- compute deltas when profiling is enabled
- local paths or viewer URL when a bundle is generated

Examples:

- `uv run python -m app.bench selectors --mode smoke`
- `uv run python -m app.bench inspect --mode quick --baseline-ref auto --output-json auto`
- `uv run python -m app.bench run --mode quick --baseline-ref auto --missing-baseline seed`
- `uv run python -m app.bench bundle --mode quick --baseline-ref auto --missing-baseline seed --goal-summary "Validate terminal tuning"`
- `uv run python -m app.bench bundle --mode focused --selectors boost:flat:far:half --seed-spec 0-4 --context-note "Testing boost flare retune"`
- `uv run python -m app.bench analyze --candidate-json outputs/benchmarks/<ref>/<stem>.tracepack.json`
- `uv run python -m app.bench report --candidate-json outputs/benchmarks/<ref>/<stem>.tracepack.json --compare-json outputs/benchmarks/<ref>/<stem>.compare_vs_<base>.json`
- `uv run python -m app.bench serve --port 8765`
- `uv run python -m app.bench promote --candidate-json outputs/benchmarks/<dirty>/<stem>.tracepack.json --target-ref HEAD`
