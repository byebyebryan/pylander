---
name: pylander-refactor-planner
description: Produce decision-complete refactor plans with invariants, phased rollout, validation, and optional file-level patch-set specification.
---

# Pylander Refactor Planner

Use this skill when the user wants a safe, explicit plan for structural changes.

Default output mode is `plan_only`.

## Inputs

- `refactor_goal`: target improvement and why
- `scope`: modules/files/components in scope
- optional `compat_constraints`
- optional `risk_tolerance`: `low | medium | high` (default `medium`)
- optional `output_mode`: `plan_only | plan_plus_patchset` (default `plan_only`)

## Required outputs

1. `invariants_and_risks`
- behavioral invariants that must not change
- boundary assumptions
- top risks and failure modes

2. `phase_plan`
- ordered, small phases with dependencies
- expected outcome per phase
- rollback/abort criteria per phase

3. `validation_plan`
- checks per phase (`pytest`, `ruff`, focused sim/bench as needed)
- final acceptance criteria

4. `optional_patchset_spec` (only for `plan_plus_patchset`)
- file-by-file edit intent
- implementation order
- coupling notes and expected diff boundaries

## Workflow

1. Map boundaries and invariants before proposing structure changes.
2. Split work into small phases that can be validated independently.
3. Define verification commands and failure rollback points per phase.
4. Add docs/test update expectations whenever behavior or workflow changes.
5. If requested, produce a patch-set spec without executing code changes.

## Guardrails

- Do not execute code edits unless explicitly requested outside this planning step.
- Avoid mixing unrelated cleanups into the refactor scope.
- Respect bot/engine boundary rules and determinism requirements.
- Prefer reversible, incremental steps over large one-shot rewrites.
