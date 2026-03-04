---
name: pylander-plot-runner
description: Select and generate Pylander plot bundles (combined and split panels) from benchmark outputs or focused selectors, then write a manifest for downstream analysis.
---

# Pylander Plot Runner

Use this skill to generate plot artifacts for human and AI analysis.

## Inputs

- `mode`: `health | compare | focus | triage`
- `benchmark_json` (for `health`/`triage`; optional in `compare`)
- `compare_json` (for `compare`/`triage`)
- `selectors` (for `focus`)
- `bot` (default: `zem_zev`)
- `eval_mode` (default: `auto`)
- `top_n` (default: `8`)
- `plot_mode` (default: `all`)
- `plot_output` (default: `both`)
- `plot_max_side_px` (default: `1800`)
- `execute` (default: true)

## Core command

`uv run python skills/pylander-plot-runner/scripts/build_plot_pack.py --mode <mode> ...`

## Behavior

1. Build case list:
- `compare`/`triage`: prioritize new global crashes from compare report
- fallback to benchmark records with large projected-dx/fuel signals
- `focus`: use explicit selectors only
2. Generate plot command(s) per case:
- `main.py plot <selector> --plot <plot_mode> --plot-output <plot_output> --plot-max-side-px <px>`
3. Write pack manifest under `outputs/plots/pack_<ts>.json` with:
- case reasons/severity
- executed commands
- generated plot paths and bundle metadata

## Notes

- Prefer `--plot-output both` for mixed human+AI workflows.
- Use `--plot-output split` when image complexity is the main concern.
- Keep `plot_max_side_px` around 1800 for robust ingestion quality.
