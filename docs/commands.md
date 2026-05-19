# Command Reference

Aegis Code is a controlled patch pipeline. Commands are proposal-first and mutation requires explicit confirmation.

## CLI Taxonomy

### 1. Daily Workflow Commands (Recommended)

These commands are the canonical day-to-day workflow:

- `aegis-code setup`
- `aegis-code config ...`
- `aegis-code patch ...`
- `aegis-code fix`
- `aegis-code diff`
- `aegis-code apply`
- `aegis-code status`
- `aegis-code report`
- `aegis-code doctor`
- `aegis-code next`

Recommended daily path:

1. `aegis-code setup`
2. `aegis-code config provider ...`
3. `aegis-code patch ...`
4. `aegis-code diff`
5. `aegis-code apply --check`
6. `aegis-code apply --confirm --run-tests`
7. `aegis-code status` and `aegis-code report`

### 2. Project & Workspace Commands

Project creation/scaffolding and multi-project orchestration:

- `aegis-code create`
- `aegis-code scaffold`
- `aegis-code workspace ...`

### 3. Advanced / Admin Commands (Specialized Tools)

Specialized tools for diagnostics, maintenance, and recovery:

- `aegis-code policy ...`
- `aegis-code maintain`
- `aegis-code compare`
- `aegis-code backups`
- `aegis-code restore <backup_id>`
- `aegis-code probe`
- `aegis-code usage`

### 4. Compatibility Aliases (Retained For Backward Compatibility)

- `aegis-code init` (direct project initialization command)
- `aegis-code onboard` (direct Aegis API key onboarding command)
- `aegis-code provider ...` (alias for `aegis-code config provider`)
- `aegis-code budget ...` (alias for `aegis-code config budget`)
- `aegis-code keys ...` (alias for `aegis-code config keys`)

## Inspection & Diagnostics Commands

Run `aegis-code status` first for the fastest project/run snapshot.

- `aegis-code status`: current project state and latest run summary.
- `aegis-code report`: detailed view of the latest run report.
- `aegis-code doctor`: environment and setup diagnostics.
- `aegis-code overview`: high-level project summary.
- `aegis-code probe`: stack detection and verification capability discovery.
- `aegis-code next`: recommended next actions.
- `aegis-code usage`: Aegis API usage summary.

Recommended workflow:

1. `aegis-code status`
2. `aegis-code report`
3. `aegis-code next`
4. `aegis-code doctor` / `aegis-code probe` when setup or environment looks off

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
aegis-code patch --file src/helpers.js --operation delete-block --anchor "OLD BLOCK" "delete obsolete block"
aegis-code patch --file src/helpers.js --operation replace-file "rewrite module with stronger validation"
aegis-code patch --file docs/old-notes.md --operation delete-file "delete obsolete file"
aegis-code patch --file src/notes.js --operation replace-symbol --symbol addNote "rewrite addNote with validation"
aegis-code patch --file src/notes.js --operation delete-symbol --symbol searchNotes "delete obsolete function"
aegis-code patch --file src/old_name.py --operation rename-file --target src/new_name.py "Rename this file."
aegis-code patch --file src/utils.js --operation move-file --target src/lib/utils.js "Move this file to lib."
aegis-code patch --operation batch --batch-file .aegis/batch.json
```

Options:

- `--operation {append,create-file,insert-after,insert-before,replace-block,delete-block,replace-file,delete-file,replace-symbol,delete-symbol,rename-file,move-file,batch}`: explicit controlled mutation mode.
- `--batch-file "<path>"`: batch definition JSON path (required for `--operation batch`, invalid for other operations).
- `--target "<path>"`: destination path for operations that require a secondary target (`rename-file`, `move-file`).
- `--anchor "<text>"`: required for `--operation insert-after` and `--operation insert-before` (exact line text), and `--operation replace-block` / `--operation delete-block` (exact block text).
- `--symbol "<name>"`: required for `--operation replace-symbol` and `--operation delete-symbol`.

Behavior:

- `patch` requires explicit scope (`--file` at least once).
- Generation is proposal-only; no file mutation without `apply --confirm`.
- Supported operation modes are explicit (`append`, `create-file`, `insert-after`, `insert-before`, `replace-block`, `delete-block`, `replace-file`, `delete-file`, `replace-symbol`, `delete-symbol`, `rename-file`, `move-file`, `batch`).
- `rename-file` is provider-free, requires one `--file` source and one `--target` destination, and preserves file contents exactly.
- `move-file` is provider-free, requires one `--file` source and one `--target` destination, and preserves file contents exactly.
- `batch` executes steps sequentially in a temporary workspace and emits one combined diff.
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
- Verification runs through `apply --confirm --run-tests`; there is no standalone `verify` command.

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

## Config (Preferred Namespace)

```bash
aegis-code config provider status
aegis-code config provider list
aegis-code config provider detect
aegis-code config provider preset <name>
aegis-code config provider model <tier> <provider:model>
aegis-code config budget set <amount>
aegis-code config budget status
aegis-code config budget clear
aegis-code config keys status
aegis-code config keys list
aegis-code config keys set <NAME> [VALUE] --project
aegis-code config keys set <NAME> [VALUE] --global
aegis-code config keys clear <NAME> --project
aegis-code config keys clear <NAME> --global
```

Compatibility aliases remain available:

- `aegis-code provider ...`
- `aegis-code budget ...`
- `aegis-code keys ...`

## Budget (Compatibility Alias)

```bash
aegis-code budget set <amount>
aegis-code budget status
aegis-code budget clear
```

Budget is estimate-based runtime guidance that influences mode/model selection, not exact API billing/cost tracking.

## Context

```bash
aegis-code context refresh
aegis-code context show
```

## Policy

```bash
aegis-code policy status
```

## Provider (Compatibility Alias)

```bash
aegis-code provider status
aegis-code provider list
aegis-code provider detect
aegis-code provider preset <name>
aegis-code provider model <tier> <provider:model>
```

Runtime provider support is currently `openai` and `openai-compatible`. `provider status` also shows configured provider details and a preset catalog, and explicitly marks preset-only providers that are not yet runtime-supported for execution.

## Keys (Compatibility Alias)

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
