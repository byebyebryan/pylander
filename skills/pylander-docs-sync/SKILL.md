---
name: pylander-docs-sync
description: Detect and plan fixes for documentation drift across README, docs, AGENTS, and skill workflow references after behavior or workflow changes.
---

# Pylander Docs Sync

Use this skill when code, CLI flags, workflow, or skill names changed and docs may be stale.

Default mode is diff-plan-first (no edits unless explicitly requested).

## Inputs

- `change_context`: what changed and why
- `scope`: `readme | docs | agents | all` (default `all`)
- optional `source_files`: paths that are source-of-truth for the change
- optional `baseline_ref`: git ref for diff context (default `HEAD~1` when useful)

## Required outputs

1. `drift_report`
- file + section
- mismatch summary
- evidence (`measured` vs `inferred`)
- severity: `blocking | important | nice_to_have`

2. `patch_plan`
- exact target files and section anchors
- explicit text/update intent for each change
- ordering to keep docs internally consistent

3. `open_questions`
- only include blockers that cannot be resolved from repo evidence

## Source-of-truth order

1. Changed behavior in code/config/tests.
2. `README.md` command model and skill inventory.
3. `docs/skills_workflow.md` workflow matrix and artifact references.
4. `docs/README.md` index pointers.
5. `AGENTS.md` workflow and definition-of-done guidance.

## Workflow

1. Collect likely drift areas from changed files and command/skill references.
2. Compare source-of-truth behavior to docs sections in scope.
3. Build `drift_report` with concrete evidence for each mismatch.
4. Build minimal `patch_plan` to restore consistency without expanding scope.
5. If requested, apply the plan and re-run a final docs sync check.

## Guardrails

- Do not invent behavior not present in code or existing docs.
- Clearly mark measured facts vs inferences.
- Keep edits minimal and scoped to drift.
- Preserve existing tone/structure unless consistency requires small rewrites.
