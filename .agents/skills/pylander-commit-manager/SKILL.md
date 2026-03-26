---
name: pylander-commit-manager
description: Plan and execute task-scoped commits with standardized messages and explicit staging boundaries for Pylander.
---

# Pylander Commit Manager

Use this skill when preparing commits for local history quality.

Commit policy for this repo: each commit should map to one problem/goal/task (PR-like scope), not split by file type.

## Inputs

- `goal_summary`: what this commit set should solve
- optional `validation_scope`: `targeted | full` (default `targeted`)
- optional `split_preference`: default task/goal-based split

## Required outputs

1. `commit_plan`
- ordered commit boundaries by goal/task
- include rationale for each split

2. `staging_plan`
- exact file list per commit
- explicit note if coupling forces a combined commit

3. `message_drafts`
- one message draft per commit using repo template

4. `execution_steps`
- exact non-interactive git commands to stage, review, and commit

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

2. Build a task/goal split plan:
- split only when goals are genuinely distinct
- keep code/tests/docs together when they support the same goal
- do not split by file category alone

3. Draft commit messages using the template.

4. Execute each commit (non-interactive):
- stage only files for one planned boundary
- review staged diff
- commit with drafted message

5. Verify state after each commit:
- `git status --short`
- if more planned commits remain, repeat

## Execution command pattern

Use non-interactive commands:

- `git add <paths...>`
- `git diff --staged`
- `git commit -m "<type>: <summary>" -m "Why:\n...\n\nWhat:\n- ...\n\nValidation:\n- ..."`

## Guardrails

- Avoid interactive staging workflows.
- If one file contains inseparable work across goals, keep it in one commit and explain coupling in `Why`.
- Keep commit scope meaningful and reviewable.
- Do not commit generated local artifacts under `outputs/`.
