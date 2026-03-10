---
name: pylander-benchmark-analyzer
description: Diagnose Pylander benchmark outcomes (health and regressions), rank likely root causes, and generate reproducible sim/plot commands for investigation.
---

# Pylander Benchmark Analyzer

Use this skill when the user wants diagnosis, not just benchmark execution.

This skill is for:

- single-pack health checks (no baseline required)
- baseline-vs-candidate regression analysis
- focused deep dives on suspicious selectors/seeds
- ranked triage with likely causes and next actions

## Inputs

- `mode`: `health | compare | focus | triage`
- `pack_mode`: `smoke | quick | full | focused`
- `bot` (default `pdg`)
- `bot_config_path` (optional JSON override path; forwarded as `--bot-config`)
- `baseline_ref` (required for `compare`)
- `seed_spec` (optional)
- `selectors` (required for `pack_mode=focused`)
- `exclude_levels` (optional)
- `observe_only_levels` (optional)
- `workers` (optional; defaults to CLI behavior)
- `max_cases` (optional; default 8)
- `auto_plot_top_n` (optional; default 3 in `triage`)

## Data Sources

Primary source:

- `skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py`

Secondary source:

- `main.py plot` and `main.py sim --freq 1` for targeted reproduction.

Cache location:

- `outputs/benchmarks/<commit-or-dirty-workspace-key>/...`

Do not commit benchmark output artifacts.

## Command Templates

Candidate-only health run:

`uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode <pack_mode> --bot <bot> [--bot-config <path>] --bot-profile --no-bot-profile-logs`

Compare against baseline:

`uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode <pack_mode> --baseline-ref <baseline_ref> --bot <bot> [--bot-config <path>] --bot-profile --no-bot-profile-logs`

Focused run:

`uv run python skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py --mode focused --selectors <selector...> --seed-spec <seed_spec> --bot <bot> [--bot-config <path>] --bot-profile --no-bot-profile-logs`

Per-case reproduction:

- `uv run python main.py plot <level[:scenario[:goal[:seed]]]> --bot <bot> --plot all`
- `uv run python main.py sim <level[:scenario[:goal[:seed]]]> --bot <bot> --freq 1`
- `PYLANDER_BOT_PROFILE=1 uv run python main.py sim <selector> --bot <bot> --freq 1`

## Mode Workflow

### `health`

1. Run or reuse a candidate benchmark pack.
2. Summarize:
- success/crash counts and rates
- primary fuel (`success_only` when available) and all-runs fuel
- compute timing (`avg`, `p90`, `p99`) for total/passive/update ms per tick
3. Flag issues by severity:
- crashes
- low success rate
- high fuel outliers
- high setup/coast projected-dx error
- compute spike risk (`p99` notably above baseline norms for that pack)
4. Emit top suspect runs and repro commands.

### `compare`

1. Run cached compare against `baseline_ref`.
2. Use compare JSON/report as source of truth.
3. Separate findings:
- global (`normal`) findings: gating
- observation (`observe_only`/`excluded`) findings: non-gating
4. Report notable regressions with evidence and repro.

### `focus`

1. Use explicit selectors/seeds only.
2. Prefer full plotting and per-frame sim logs for top cases.
3. Return concise root-cause hypotheses tied to measured signals and plot shape.

### `triage`

1. Rank candidate issues by severity then impact.
2. Prioritize:
- new global crashes
- large global success-rate drop
- major fuel regression with stable success
- notable compute regression (`avg` or `p99`)
- trajectory-shape anomalies
3. Return an investigation order and first-fix recommendation.
4. Hybrid auto plot policy:
- auto-generate plots for top 3 critical cases
- provide manual plot commands for remaining cases

## Diagnostic Heuristics

Use these heuristics consistently.

### Crash and Success

- `new global crashes > 0` is critical.
- Observation-only crashes are reported but non-gating.
- Success-rate drop without fuel gain indicates instability regression.

### Fuel

- Compare both `fuel_mean_primary` and `fuel_mean_all`.
- Prefer success-only fuel for core efficiency interpretation.
- Use all-runs fuel to explain crash/outlier skew.

### Trajectory/Phase Quality

Use available gate and ZEM fields to detect shaping issues:

- high `|setup_gate_projected_dx|` suggests poor setup handoff
- high `|bot_<botname>_flare_entry_projected_dx|` suggests insufficient passive alignment
- large gap between setup and flare-entry projected-dx suggests heavy late correction burden
- large `bot_pdg_shape_curve_rmse` / `bot_pdg_shape_apex_error` suggests trajectory shape mismatch
- gate ordering anomalies (for runs with both timestamps) indicate phase/control bugs

### Compute

Use bot profile fields from benchmark output:

- `bot_profile_total_ms_per_tick`
- `bot_profile_total_ms_per_tick_p90`
- `bot_profile_total_ms_per_tick_p99`
- passive/update equivalents

Treat sustained avg increase and p99 spike increase as separate signals.

## Output Contract

Always return:

1. diagnostic verdict (`doctor_verdict`): `healthy | watch | investigate | critical`
2. `top_findings`: ranked, each with:
- severity
- signal/metric evidence
- likely cause
- confidence (`low|medium|high`)
3. `repro_bundle`: exact `plot`/`sim` commands for top cases
4. `next_actions`: concrete next checks or tuning moves

## Response Style

- Be explicit about what is measured vs inferred.
- Keep summaries tight; prioritize actionable findings.
- When plots are available, tie metric findings to visual shape anomalies.
- If data is insufficient, state what is missing and what run should be executed next.
