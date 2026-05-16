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

Core philosophy:

- AI proposes.
- Aegis controls.
- Developer decides.
- Tests verify.

## What Aegis Code Is Not

Aegis Code is not:

- an autonomous coding agent
- a replacement for developer review
- a blind patch applier
- a guarantee that every generated patch is correct

## Controlled Mutation Architecture

Aegis Code is provider-agnostic and proposal-first. Runtime orchestration and operation execution are intentionally separated so mutation intent is explicit and enforceable.

Current validated operations:

- `append`
- `create-file`
- `insert-after`
- `insert-before`
- `replace-block`
- `delete-block`
- `replace-file`
- `delete-file`
- `replace-symbol`
- `delete-symbol`
- `rename-file`
- `move-file`

Canonical source of truth:

- `aegis_code/operations/registry.py` defines supported operation names and operation metadata used by CLI, scope, and runtime gates.

Architecture overview:

`CLI -> Runtime -> Operation Stage -> Operation Runner -> Operation Module -> Local Diff Validation -> Report -> Apply`

Extension path:

- Add a new operation module with local validation semantics.
- Register the operation metadata in `aegis_code/operations/registry.py`.
- Add prompt builder(s) under `aegis_code/providers/prompts/` when needed.
- Register dispatch in the operation runner.
- Add runtime/operation tests and update docs.

## Core Workflow

1. Generate a scoped patch proposal (no file mutation):

```bash
aegis-code patch --file src/example.py "fix failing tests"
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
- Explicit operation intent: operation mode is user-declared and contract-checked for scoped patch flows.
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
- Validation path includes diff inspection, operation-specific checks, and patch safety scoring.
- No git commands are run by Aegis Code.
- Stale diff cleanup: task runs clear prior `latest.diff` / `latest.invalid.diff` before new generation.

## Patch Command (Scoped Proposals)

`aegis-code patch` is the preferred proposal command for bounded edits.

```bash
aegis-code patch --file src/example.py "fix bug in parser"
aegis-code patch --file README.md --operation append "add usage examples"
aegis-code patch --file src/helpers.js --operation create-file "create helper module"
aegis-code patch --file src/helpers.js --operation insert-after --anchor "// ANCHOR" "insert helper after anchor"
aegis-code patch --file src/helpers.js --operation insert-before --anchor "// ANCHOR" "insert helper before anchor"
aegis-code patch --file src/helpers.js --operation replace-block --anchor "OLD BLOCK" "replace block with safer implementation"
aegis-code patch --file src/helpers.js --operation delete-block --anchor "OLD BLOCK" "delete obsolete block"
aegis-code patch --file src/helpers.js --operation replace-file "rewrite module with stronger validation"
aegis-code patch --file docs/old-notes.md --operation delete-file "delete obsolete file"
aegis-code patch --file src/notes.js --operation replace-symbol --symbol addNote "rewrite addNote with validation"
aegis-code patch --file src/notes.js --operation delete-symbol --symbol searchNotes "delete obsolete function"
aegis-code patch --file src/old_name.py --operation rename-file --target src/new_name.py "Rename this file."
aegis-code patch --file src/utils.js --operation move-file --target src/lib/utils.js "Move this file to lib."
```

Behavior:

- Requires explicit scope: at least one `--file`.
- Uses proposal-only generation and validation; no mutation without `apply --confirm`.
- Supported explicit operations: `append`, `create-file`, `insert-after`, `insert-before`, `replace-block`, `delete-block`, `replace-file`, `delete-file`, `replace-symbol`, `delete-symbol`, `rename-file`, `move-file`.
- `--anchor` is required for `--operation insert-after` and `--operation insert-before` (exact line), and for `--operation replace-block` / `--operation delete-block` (exact block text).
- `--symbol` is required for `--operation replace-symbol` and `--operation delete-symbol`.
- `--target` is required for `--operation rename-file` and `--operation move-file` (destination path).
- `replace-file` rewrites complete file contents for an explicit existing target, with local diff validation and normal safety/apply gates.
- `delete-file` is provider-free and removes one explicit existing target via local diff generation and validation.
- `replace-symbol` rewrites one uniquely resolved symbol in one explicit existing target, with local diff validation and normal safety/apply gates.
- `delete-symbol` is provider-free and removes one uniquely resolved symbol in one explicit existing target, with local diff validation and normal safety/apply gates.
- `rename-file` is provider-free and renames one explicit existing source path to a new destination path while preserving file contents exactly.
- `move-file` is provider-free and moves one explicit existing source path to a new destination path while preserving file contents exactly.
- For additive docs tasks without explicit append mode, CLI prints guidance to rerun with `--operation append` (no automatic operation inference).
- Runtime reports preserve operation metadata (`patch_operation.operation`, `patch_operation.source`) for diagnostics and auditing.

## Fix Loop

Use bounded test-fix workflow:

```bash
aegis-code fix
aegis-code fix --confirm
aegis-code fix --confirm --max-cycles 2
```

Behavior:

- `fix` without `--confirm` is non-mutating.
- `fix` can produce a bounded usable patch without applying it (`Status: GENERATED`, `Reason: bounded_patch_ready`).
- `fix --confirm` applies only when patch checks/safety gates permit.
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

Scoped patch proposal:

```bash
aegis-code patch --file src/example.py "fix edge case in parser"
aegis-code patch --file tests/test_example.py --operation append "add regression test"
aegis-code patch --file README.md --operation append "add README usage examples"
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

Runtime awareness:

- Workspace-aware: scoped runs honor per-project config, context, and verification settings.
- Budget-aware: mode/control signals can adapt based on configured local budget state.
- Provider-agnostic: provider integration is pluggable; control and safety gates stay local and deterministic.

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

Recommended defaults:

- Use `--global` for `AEGIS_API_KEY` and provider keys such as `OPENAI_API_KEY`.
- Use `--project` for repository-specific secrets only.
- Environment variables still take precedence over stored keys.

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

