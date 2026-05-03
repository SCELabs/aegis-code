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
- `fix --confirm` only applies accepted `HIGH`/`MEDIUM` patches.
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
