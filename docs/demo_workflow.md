# Demo Workflow

## A. Setup

```bash
pip install -e .
aegis-code init
export AEGIS_API_KEY="..."
```

Optional SLL:

```bash
pip install -e ../structural-language-lab
aegis-code --check-sll
```

## B. Normal run

```bash
aegis-code "triage current test failures" --budget 1.25
aegis-code report
aegis-code status
```

## C. Failure + proposal workflow

1. Manually create a temporary failing test.
2. Run:

```bash
aegis-code "triage current test failures" --budget 1.25 --propose-patch
aegis-code report
aegis-code apply --check .aegis/runs/latest.diff
aegis-code apply .aegis/runs/latest.diff
aegis-code apply .aegis/runs/latest.diff --confirm
aegis-code backups
aegis-code restore BACKUP_ID
```

## D. Safety guarantees

- No auto-apply.
- `--confirm` required for file changes.
- Confirmed apply creates backups.
- Restore is available.
- No git commands are run.

