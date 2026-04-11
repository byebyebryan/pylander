---
name: pylander-commit-manager
description: Plan and execute task-scoped commits with standardized messages and explicit staging boundaries for Pylander.
---

# Pylander Commit Manager

Use this skill when preparing one or more commits from an existing working tree.

Keep it grounded in the current repo state:

- inspect the working tree before proposing commit boundaries
- split by goal or behavior change, not by file category
- keep code, tests, and docs together when they serve the same change
- prefer one commit per reviewable task unless the working tree clearly contains multiple independent goals

## Message template

Subject:
- `<type>: <goal summary>`
- types: `feat | fix | refactor | docs | test | bench | skills | chore`
- imperative mood
- max 72 chars

Body (for non-trivial commits, and recommended generally):

`Why:`
- 1-2 lines on problem/intent

`What:`
- 2-4 bullets covering major changes

`Validation:`
- exact commands run, or `not run` with reason

## Workflow

1. Inspect pending changes:
- `git status --short`
- `git diff --name-only`
- `git diff --staged --name-only`

2. Choose commit boundaries:
- split only when goals are genuinely distinct
- if one file couples multiple edits inseparably, keep them in the same commit

3. Draft the commit message for each boundary.

4. Execute each commit non-interactively:
- stage only files for one planned boundary
- review staged diff
- commit with drafted message

5. If the commit finalizes a change that was already benchmarked on a dirty workspace, consider promoting the cached benchmark explicitly:
- `uv run python -m bot_framework.bench promote --candidate-json outputs/benchmarks/<dirty>/<stem>.tracepack.json --target-ref HEAD`

6. Verify state after each commit:
- `git status --short`
- if more planned commits remain, repeat

## Execution pattern

Use plain git commands:

- `git add <paths...>`
- `git diff --staged`
- `git commit -m "<type>: <summary>" -m "Why:\n...\n\nWhat:\n- ...\n\nValidation:\n- ..."`

## Guardrails

- Avoid interactive staging workflows.
- Keep commit scope meaningful and reviewable.
- Do not commit generated local artifacts under `outputs/`.
