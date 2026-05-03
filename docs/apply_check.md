# Apply Check (Preview-Only)

`aegis-code apply --check` validates a patch without modifying files.

## Commands

```bash
aegis-code apply --check
aegis-code apply --check <path>
```

Behavior:

- `--check` with no path validates `.aegis/runs/latest.diff`.
- If no accepted diff exists but `.aegis/runs/latest.invalid.diff` exists, apply remains blocked.
- Reports validity, counts, warnings, and apply-block reasons.
- For latest accepted diff, run-level safety gating applies:
  - `LOW` -> blocked (`low_safety`)
  - `BLOCKED` -> blocked (`blocked_safety`)

## What apply check does not do

- Does not apply patches.
- Does not edit files.
- Does not run git operations.

## Safety notes

- `latest.invalid.diff` is inspectable via `aegis-code diff --full` but never applyable.
- Use `aegis-code diff`, `--stat`, or `--full` before confirm apply.
