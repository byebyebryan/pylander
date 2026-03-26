---
name: pylander-plot-runner
description: Select and generate Pylander trace-first focused galleries from benchmark outputs or manual selectors, then write a manifest for downstream analysis.
---

# Pylander Plot Runner

Use this skill to generate plot artifacts for human and AI analysis.

If the user asks for "the plots" or wants something clickable/openable remotely,
default to the static HTML bundle workflow instead of returning raw PNG paths.
For benchmark-backed requests, prefer:

`uv run python .agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py ...`

That wrapper:
- generates the benchmark summary page plus interactive trace-backed detail pages
- checks whether the outputs web server is already running
- starts it in the background if needed
- returns a reachable latest URL (preferring the machine's `.lan` hostname when available)
- uses pre-rendered preview thumbnails in tables and interactive charts on the detail pages

When the user says "full bench and plots", interpret that as:
- `--mode full`
- benchmark coverage across the current full auto-pack levels (`plunge`, `boost`, `terminal`)
- interactive detail pages for every run in the pack

Use raw `build_plot_pack.py` directly only when the caller explicitly wants a
plot-pack manifest or a focused manual selector gallery without benchmark
summary context.

## Inputs

- `mode`: `health | compare | focus | triage`
- `benchmark_json` (for `health`/`triage`; optional in `compare`)
- `compare_json` (for `compare`/`triage`)
- `selectors` (for `focus`)
- `bot` (default: `pdg`)
- `top_n` (default: `8`)
- `trace_sample_period_s` (default: `0.25` for `main.py plot`)
- `trace_detail` (default: `debug` for `main.py plot`)
- `execute` (default: true)

## Core command

`uv run python .agents/skills/pylander-plot-runner/scripts/build_plot_pack.py --mode <mode> ...`

Preferred remote-sharing command for benchmark-backed requests:

`uv run python .agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py --mode <pack_mode> ...`

## Behavior

1. Build case list:
- `compare`/`triage`: prioritize new global crashes from compare report
- fallback to benchmark records with large generic boost-cutoff miss, bot-owned terminal-entry miss, or fuel signals
- `focus`: use explicit selectors only
2. Generate plot command(s) per case:
- `main.py plot <selector> --trace-sample-period-s <seconds> --trace-detail debug`
3. Write pack manifest under `outputs/viewer/plot-packs/pack_<ts>/manifest.json` with:
- case reasons/severity
- executed commands
- trace paths, preview paths, and HTML detail/gallery metadata

Remote-share default:

4. If the user asked to "give me the plots", generate the HTML bundle and
return the stable latest URL instead of only listing files.

## Notes

- The benchmark/report workflow is trace-first; PNGs remain only as small preview thumbnails.
- `plot` defaults to `debug` traces; benchmark bundles default to lean `report` traces.
- Current triage ranking uses `boost_cutoff_projected_dx` and the selected bot's
  `bot_<botname>_terminal_entry_projected_dx` when available.
