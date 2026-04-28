# Apply Confirm (Human-Confirmed)

Use explicit confirmation to apply a patch diff:

- `aegis-code apply .aegis/runs/latest.diff --confirm`
- `aegis-code apply .aegis/runs/latest.diff` (preview only, no edits)

## Safety model
- Requires explicit `--confirm`.
- Runs patch inspection/check before apply.
- Refuses invalid or unsafe diffs.
- Creates backups under `.aegis/backups/<timestamp>/...`.
- Does not run git commands.

## Limitations
- Text unified diffs only.
- No binary diff apply.
- No rename/delete/new-file apply in this phase.
- No autonomous apply behavior.

## Recovery
- Restore files manually from `.aegis/backups/...` if needed.
- List backups: `aegis-code backups`
- Restore backup snapshot: `aegis-code restore BACKUP_ID`
