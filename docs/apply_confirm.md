# Apply Confirm (Human-Confirmed)

Use explicit confirmation to apply a patch:

```bash
aegis-code apply --confirm
aegis-code apply --confirm <path>
aegis-code apply --confirm --run-tests
```

## Behavior

- `--confirm` is required for file mutation.
- No-path confirm applies `.aegis/runs/latest.diff`.
- If latest accepted diff is missing:
  - and latest invalid diff exists, apply is blocked.
  - otherwise, apply reports no accepted diff.
- `LOW` or `BLOCKED` latest run safety blocks apply.
- `--run-tests` runs configured tests after successful apply.

## Safety model

- Validates patch structure before apply.
- Refuses invalid/unsafe patches.
- Creates backups under `.aegis/backups/<id>/...`.
- No git commands are run.

## Limitations

- Unified text diffs only.
- `latest.invalid.diff` is never applyable.
- Review remains required; apply is not autonomous.

## Recovery

```bash
aegis-code backups
aegis-code restore <backup-id>
```
