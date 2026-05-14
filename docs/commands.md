# Command Reference

Aegis Code is a controlled patch pipeline. Commands are proposal-first and mutation requires explicit confirmation.

## Project

```bash
aegis-code init
aegis-code setup
aegis-code setup --check
aegis-code next
aegis-code overview
aegis-code status
aegis-code report
aegis-code compare
aegis-code maintain
```

## Runtime Task

```bash
aegis-code "<task>"
aegis-code "<task>" --dry-run
aegis-code "<task>" --propose-patch
```

## Patch (Explicit Scope)

```bash
aegis-code patch --file <path> "<task>"
aegis-code patch --file <path> --file <path> "<task>"
aegis-code patch --file README.md --operation append "add usage examples"
aegis-code patch --file tests/test_example.py --operation append "add tests"
aegis-code patch --file src/helpers.js --operation create-file "create helper module"
aegis-code patch --file src/helpers.js --operation insert-after --anchor "// ANCHOR" "insert helper after anchor"
aegis-code patch --file src/helpers.js --operation insert-before --anchor "// ANCHOR" "insert helper before anchor"
aegis-code patch --file src/helpers.js --operation replace-block --anchor "OLD BLOCK" "replace block with safer implementation"
```

Options:

- `--operation {append,create-file,insert-after,insert-before,replace-block}`: explicit controlled mutation mode.
- `--anchor "<text>"`: required for `--operation insert-after` and `--operation insert-before` (exact line text), and `--operation replace-block` (exact block text).

Behavior:

- `patch` requires explicit scope (`--file` at least once).
- Generation is proposal-only; no file mutation without `apply --confirm`.
- Supported operation modes are explicit (`append`, `create-file`, `insert-after`, `insert-before`, `replace-block`).
- No operation inference: additive docs/test tasks without `--operation append` stay in normal flow, but CLI prints stronger rerun guidance.
- Append mode supports no-op signal (`{"content": ""}`) and can block with `no_append_needed`.
- Docs/test destructive rewrite protections can block proposals (`destructive_docs_rewrite`, `destructive_test_rewrite`).

## Diff Inspection

```bash
aegis-code diff
aegis-code diff --stat
aegis-code diff --full
```

Behavior:

- `diff` reads `.aegis/runs/latest.diff` when present.
- If `latest.diff` is missing and `.aegis/runs/latest.invalid.diff` exists, it shows the invalid diff with BLOCKED labeling.

## Apply

```bash
aegis-code apply --check
aegis-code apply --check <path>
aegis-code apply --confirm
aegis-code apply --confirm <path>
aegis-code apply --confirm --run-tests
```

Behavior:

- `--check` is non-mutating.
- `--confirm` is required for mutation.
- Applying defaults to `.aegis/runs/latest.diff` when no path is provided.
- `latest.invalid.diff` is never applyable.
- For latest accepted diff, `LOW`/`BLOCKED` apply safety is blocked by `apply --check` and `apply --confirm`.

## Fix Loop

```bash
aegis-code fix
aegis-code fix --confirm
aegis-code fix --confirm --max-cycles 2
aegis-code fix --max-cycles 3
```

Behavior:

- `fix` without `--confirm` does not mutate files.
- `fix` may return a usable bounded proposal without applying it:
  - `Status: GENERATED`
  - `Reason: bounded_patch_ready`
- `fix --confirm` applies only when patch checks and safety gates allow it.
- Bounded loop stops on repeated failure signatures and max cycles.
- Deterministic assertion micro-fix is available for simple single-test assertion mismatch cases.

## Budget

```bash
aegis-code budget set <amount>
aegis-code budget status
aegis-code budget clear
```

Budget is a runtime control signal, not real API billing/cost tracking.

## Context

```bash
aegis-code context refresh
aegis-code context show
```

## Policy

```bash
aegis-code policy status
```

## Provider

```bash
aegis-code provider status
aegis-code provider list
aegis-code provider detect
aegis-code provider preset <name>
aegis-code provider model <tier> <provider:model>
```

## Keys

```bash
aegis-code keys status
aegis-code keys list
aegis-code keys set <NAME> [VALUE] --project
aegis-code keys set <NAME> [VALUE] --global
aegis-code keys clear <NAME> --project
aegis-code keys clear <NAME> --global
```

## Create

```bash
aegis-code create --list-stacks
aegis-code create "<idea>"
aegis-code create "<idea>" --stack <stack-id>
aegis-code create "<idea>" --target <path>
aegis-code create "<idea>" --target <path> --confirm
aegis-code create "<idea>" --target <path> --confirm --validate
```

## Workspace

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
