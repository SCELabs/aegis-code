# Apply Check (Preview-Only)

`aegis-code apply --check` validates a diff file without modifying project files.

## What apply check does
- Reads a diff file.
- Parses file targets, hunks, additions, and deletions.
- Reports summary counts.
- Surfaces warnings and errors.

## What apply check does NOT do
- It does not apply patches.
- It does not edit files.
- It does not run git operations.

## Command examples
- `aegis-code apply --check .aegis/runs/latest.diff`

## Safety guarantees
- No file edits are performed.
- No patch application occurs.
- No git operations are performed.

## Future note
- A real apply command may be added later behind explicit human confirmation.

