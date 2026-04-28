# Apply Check (Preview-Only)

`aegis-code apply --check` validates a diff file without modifying project files.

## What apply check does
- Reads a diff file.
- Parses file targets, hunks, additions, and deletions.
- Reports summary counts.
- Surfaces warnings and errors.
- If the diff file is missing, prints a setup hint to generate a proposal diff first.

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

## Warning categories
- `unsafe_absolute_path`: diff references absolute paths.
- `unsafe_parent_traversal`: diff references parent traversal (`..`) paths.
- `internal_or_generated_path`: diff touches internal/generated paths such as:
  `.git`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `*.egg-info`, `.aegis`.
- `very_large_diff`: more than 1000 changed lines.
- `binary_diff_detected`: binary patch markers detected.

Warnings do not apply or block anything by themselves. They are advisory for human review.

## Future note
- A real apply command may be added later behind explicit human confirmation.
