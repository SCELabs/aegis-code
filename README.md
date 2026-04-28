# aegis-code

`aegis-code` is a terminal-native, Aegis-guided coding workflow runner focused on safe, supervised operation.

Current capabilities include failure-aware test triage, optional structural analysis, proposal-only patch diffs, deterministic patch-quality scoring, and explicit human-confirmed apply with backups.

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

Show latest report:

```bash
aegis-code report
```

Show compact workflow status:

```bash
aegis-code status
```

## Command Index

- `aegis-code init` - create `.aegis` config/project model files
- `aegis-code "<task>"` - run controlled failure-aware workflow
- `aegis-code report` - print latest markdown report
- `aegis-code status` - compact latest-run summary
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

## Optional Integrations

- SLL (`structural_language_lab`) is optional and local-install only.
- Provider-backed patch diffs are optional and proposal-only.
