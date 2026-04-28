# Maintain Command

`aegis-code maintain` provides a read-only repo health summary from local state.

## What It Does

- Detects verification capability and configured test command.
- Reads the latest run report (`.aegis/runs/latest.json`) when present.
- Summarizes structural signals from latest `sll_analysis` if available.
- Reports hygiene signals like run artifact count and backup count.
- Suggests safe next actions.

## What It Does Not Do

- Does not run tests.
- Does not call Aegis.
- Does not call providers.
- Does not edit files.
- Does not run git commands.

## Command

```bash
aegis-code maintain
```

## How It Differs

- `doctor`: capability and integration setup snapshot.
- `status`: latest run summary.
- `fix`: supervised repair flow.
- `maintain`: proactive, read-only repo health suggestions.
