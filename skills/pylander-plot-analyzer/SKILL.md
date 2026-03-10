---
name: pylander-plot-analyzer
description: Analyze Pylander plot bundles from a plot-pack manifest, rank visual anomalies, and map them to likely control/phase issues.
---

# Pylander Plot Analyzer

Use this skill to interpret generated plot bundles.

## Input

- `plot_pack_manifest` (required)
- optional `benchmark_json` for metric cross-reference

## Workflow

1. Read pack manifest and enumerate bundle files per case.
2. Analyze split panels first (`spatial_*`, `timeseries_*`), then use combined overview for context.
3. Produce ranked findings with evidence:
- trajectory undershoot/overshoot patterns
- late correction burden
- setup/coast handoff quality hints
- thrust-vector instability or flare-phase clutter patterns
4. Return follow-up commands (`sim`, profiled `sim`, focused re-plot) for top issues.

## Output contract

- diagnostic verdict (`doctor_verdict`): `healthy | watch | investigate | critical`
- ranked findings with severity and confidence
- observed signals vs inferred cause separation
- actionable next steps

## Guardrails

- If image evidence is ambiguous, call it out explicitly.
- Prefer reproducible follow-ups over speculative root causes.
- Use benchmark metrics to corroborate visual conclusions when available.
