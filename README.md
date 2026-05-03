# aegis-code

A terminal-native controlled patch pipeline for proposing, inspecting, validating, and safely applying code changes.

## What Aegis Code Is

Aegis Code is a safety/control layer around AI-assisted patch generation. It is designed to:

- generate proposal diffs
- validate and inspect patches
- attempt conservative repair for specific malformed diffs
- block unsafe or invalid patches
- require explicit human confirmation before file mutation
- optionally verify with tests after apply

## What Aegis Code Is Not

Aegis Code is not:

- an autonomous coding agent
- a replacement for developer review
- a blind patch applier
- a guarantee that every generated patch is correct

## Core Workflow

1. Generate a proposal (no file mutation):

```bash
aegis-code "fix failing tests" --propose-patch
```

2. Inspect the latest diff:

```bash
aegis-code diff
aegis-code diff --stat
aegis-code diff --full
```

3. Run apply check:

```bash
aegis-code apply --check
```

4. Apply only with explicit confirmation:

```bash
aegis-code apply --confirm
```

5. Apply and run tests:

```bash
aegis-code apply --confirm --run-tests
```

## Quickstart

Install (dev):

```bash
pip install -e .
```

Initialize project files:

```bash
aegis-code init
```

Setup readiness check:

```bash
aegis-code setup --check
```

Refresh and inspect local runtime context:

```bash
aegis-code context refresh
aegis-code context show
```

Propose + inspect + check + apply:

```bash
aegis-code "triage current test failures" --propose-patch
aegis-code diff
aegis-code apply --check
aegis-code apply --confirm --run-tests
```

## Safety Model

- Proposal-first: generation is proposal-only.
- No silent apply: `--confirm` is required for mutation.
- Accepted vs invalid diffs:
  - accepted diff: `.aegis/runs/latest.diff`
  - invalid diff: `.aegis/runs/latest.invalid.diff`
- `aegis-code diff` prefers `latest.diff`; if missing, it shows `latest.invalid.diff` with a BLOCKED warning.
- Apply safety scoring is written to run metadata:
  - `HIGH`, `MEDIUM`, `LOW`, `BLOCKED`
- `apply --check` and `apply --confirm` gate on latest run safety for `latest.diff`:
  - `LOW` and `BLOCKED` are blocked.
- Hard-invalid guards block placeholder/truncation content and destructive rewrites.
- Destructive rewrite protection includes tests/docs-focused guards.
- No git commands are run by Aegis Code.
- Stale diff cleanup: task runs clear prior `latest.diff` / `latest.invalid.diff` before new generation.

## Fix Loop

Use bounded test-fix workflow:

```bash
aegis-code fix
aegis-code fix --confirm
aegis-code fix --confirm --max-cycles 2
```

Behavior:

- `fix` without `--confirm` is non-mutating.
- `fix --confirm` only applies accepted diffs with `HIGH`/`MEDIUM` safety.
- Stops early on repeated failure signatures to avoid loops.
- For simple single-test pytest assertion mismatches, Aegis Code can use a deterministic micro-fix (single assertion update) instead of provider generation.
- Deterministic micro-fixes still go through diff/check metadata and safety gating.

## Command Reference

Project and status:

```bash
aegis-code init
aegis-code setup
aegis-code setup --check
aegis-code status
aegis-code report
aegis-code compare
aegis-code overview
aegis-code next
```

Runtime/task:

```bash
aegis-code "<task>"
aegis-code "<task>" --dry-run
aegis-code "<task>" --propose-patch
```

Diff/apply/fix:

```bash
aegis-code diff
aegis-code diff --stat
aegis-code diff --full
aegis-code apply --check
aegis-code apply --check <path>
aegis-code apply --confirm
aegis-code apply --confirm <path>
aegis-code apply --confirm --run-tests
aegis-code fix
aegis-code fix --confirm --max-cycles 2
```

Context/budget/policy:

```bash
aegis-code context refresh
aegis-code context show
aegis-code budget set 1.00
aegis-code budget status
aegis-code budget clear
aegis-code policy status
```

Workspace:

```bash
aegis-code workspace init
aegis-code workspace add <path>
aegis-code workspace remove <path>
aegis-code workspace status
aegis-code workspace status --detailed
aegis-code workspace overview
aegis-code workspace refresh-context
aegis-code workspace run "<task>" --dry-run
aegis-code workspace run "<task>" --confirm
```

## Keys, Project Scope, and Workspace

Aegis Code supports project and global key management via `aegis-code keys`.

- project scope: stored for current project
- global scope: reusable across projects/workspaces

Examples:

```bash
aegis-code keys status
aegis-code keys list
aegis-code keys set OPENAI_API_KEY --project
aegis-code keys set OPENAI_API_KEY --global
aegis-code keys clear OPENAI_API_KEY --project
```

Workspace operations reuse each project's local config, context, and runtime controls.

## Budget Control Note

Budget in Aegis Code is a runtime control signal for behavior (for example mode selection and control policy), not a real billing/cost tracker.

## Current Limitations

- Python-first workflow today.
- Provider output quality can vary.
- Complex semantic fixes may still block or require task refinement/manual edits.
- Node/JS support is planned but not complete.

## Demo Script (Failing-Test Flow)

```bash
pip install -e .
aegis-code init
aegis-code setup --check
aegis-code context refresh

# run a proposal-producing task
aegis-code "fix failing tests" --propose-patch

# inspect proposal

aegis-code diff --stat
aegis-code diff

# validate apply safety
aegis-code apply --check

# apply with explicit confirmation + test verification
aegis-code apply --confirm --run-tests
```

If latest patch is invalid/blocked, inspect raw provider diff:

```bash
aegis-code diff --full
```

## Documentation

- Command reference: `docs/commands.md`
- Apply check: `docs/apply_check.md`
- Apply confirm: `docs/apply_confirm.md`
- Workspace: `docs/workspace.md`
- Providers and keys: `docs/providers.md`
- Create workflow: `docs/create.md`
- Demo workflow: `docs/demo_workflow.md`
