# aegis-code

`aegis-code` is a terminal-native, Aegis-guided coding workflow runner focused on safe, supervised operation.

Current capabilities include failure-aware test triage, optional structural analysis, proposal-only patch diffs, deterministic patch-quality scoring, explicit human-confirmed apply with backups, and controlled project scaffold creation.

## Install (Dev)

```bash
pip install -e .
```

## Environment Variables

- `AEGIS_API_KEY` (optional for local smoke tests, required for real backend auth)
- `AEGIS_BASE_URL` (optional override; otherwise config/default is used)
- `OPENAI_API_KEY` (optional; only needed for provider-backed proposal diffs)

See `.env.example` for a starter template.

## Quick Start

```bash
aegis-code init
```

Run a task:

```bash
aegis-code "triage current test failures" --budget 1.25
```

List available stack profiles:

```bash
aegis-code create --list-stacks
```

Create a planning-only project plan:

```bash
aegis-code create "inventory tracker"
```

Force a stack profile:

```bash
aegis-code create "inventory tracker" --stack python-fastapi
```

Preview scaffold target without writing files:

```bash
aegis-code create "inventory tracker" --target ./inventory-api
```

Write scaffold files with explicit confirmation:

```bash
aegis-code create "inventory tracker" --target ./inventory-api --confirm
```

Write scaffold files and validate:

```bash
aegis-code create "inventory tracker" --target ./inventory-api --confirm --validate
```

## Stack Profiles

Current internal stack IDs:

- `python-basic`
- `python-cli`
- `python-fastapi`
- `node-react`

Profiles are versioned internally (starting at `0.1`) and surfaced in create planning output.

Scaffold writes `.aegis/create_manifest.yml` to record selected stack, stack version, idea, test command, and created files.

No external Copier/Cookiecutter template dependency is used yet.

`aegis-code create --list-stacks` lists internal stack profiles and versions without generating a plan or writing files.

`--validate` is optional and only runs after `--target` + `--confirm`; it runs tests for the scaffold and, on failure, runs Aegis stabilization planning/proposal flow.

## Command Index

- `aegis-code init` - create `.aegis` config/project model files
- `aegis-code "<task>"` - run controlled failure-aware workflow
- `aegis-code create --list-stacks` - list available internal stack profiles and versions
- `aegis-code create "<idea>"` - generate a planning-only project plan preview
- `aegis-code create "<idea>" --stack STACK_ID` - force a stack profile
- `aegis-code create "<idea>" --target PATH` - preview scaffold file set (no writes)
- `aegis-code create "<idea>" --target PATH --confirm` - write scaffold to empty target
- `aegis-code create "<idea>" --target PATH --confirm --validate` - scaffold, verify, and run stabilization proposal on failures
- `aegis-code report` - print latest markdown report
- `aegis-code status` - compact latest-run summary
- `aegis-code maintain` - read-only repo health and suggestions
- `aegis-code --check-sll` - verify optional SLL local import
- `aegis-code apply --check PATH` - inspect diff without modifying files
- `aegis-code apply PATH` - preview apply and require explicit confirmation
- `aegis-code apply PATH --confirm` - human-confirmed apply with backups
- `aegis-code backups` - list backup snapshots
- `aegis-code restore BACKUP_ID` - restore files from backup snapshot

## Safety Model

- No autonomous edits.
- No patch auto-apply.
- `--confirm` required for file mutation.
- Confirmed apply creates backups under `.aegis/backups/...`.
- Restore is available for rollback.
- No git commands are run by `aegis-code`.
- `create --target` refuses current repo root and non-empty targets.

## Optional Integrations

- SLL (`structural_language_lab`) is optional and local-install only.
- Provider-backed patch diffs are optional and proposal-only.
