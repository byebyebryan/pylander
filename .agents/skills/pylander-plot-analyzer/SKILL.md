---
name: pylander-plot-analyzer
description: Analyze Pylander trace-backed detail/preview views from a focused manifest, rank visual anomalies, and map them to likely control/phase issues.
---

# Pylander Plot Analyzer

Use this skill to interpret generated trace-backed detail and preview views.

## Input

- `plot_pack_manifest` (required)
- optional `benchmark_json` for metric cross-reference

## Workflow

1. Read the focused manifest and enumerate trace/detail artifacts per case.
2. Analyze per-case trace-backed detail pages and previews first, then use overview context when available.
3. Produce ranked findings with evidence:
- trajectory undershoot/overshoot patterns
- late correction burden
- boost/coast handoff quality hints
- thrust-vector instability or terminal-phase clutter patterns
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
