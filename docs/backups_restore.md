# Backups and Restore

Confirmed patch apply creates backups under `.aegis/backups/<timestamp>/...`.

## List backups
- `aegis-code backups`

## Restore a backup snapshot
- `aegis-code restore BACKUP_ID`

## Important behavior
- Restore does not delete the backup snapshot.
- Restore does not use git.
- Restore overwrites current files with backup contents.

## Safety warning
- Review restored files after running restore.

