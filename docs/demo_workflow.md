# Demo Workflow

This demo shows the controlled proposal -> inspect -> check -> confirm flow.

## A. Setup

```bash
pip install -e .
aegis-code init
aegis-code setup --check
aegis-code context refresh
```

(Optional) configure provider/Aegis keys before proposal generation.

## B. Create a failing-test scenario

Create or keep a known failing test in your project, then run:

```bash
python -m pytest -q
```

## C. Generate proposal (non-mutating)

```bash
aegis-code "fix failing tests" --propose-patch
```

## D. Inspect diff

```bash
aegis-code diff --stat
aegis-code diff
aegis-code diff --full
```

Notes:

- If `latest.diff` exists, `diff` shows accepted patch content.
- If accepted diff does not exist and `latest.invalid.diff` exists, `diff` shows the invalid patch with BLOCKED labeling.

## E. Apply check

```bash
aegis-code apply --check
```

This validates the latest accepted diff and reports apply-block reasons. `LOW`/`BLOCKED` latest safety is blocked.

## F. Confirm apply + verification

```bash
aegis-code apply --confirm --run-tests
```

## G. Fix loop (bounded)

Proposal-only fix loop:

```bash
aegis-code fix
```

Confirmed bounded fix loop:

```bash
aegis-code fix --confirm --max-cycles 2
```

Fix loop stops on repeated failure signatures and does not mutate without `--confirm`.

## Safety guarantees

- No silent apply.
- `--confirm` required for mutation.
- Backups created on apply.
- Invalid diffs are inspectable but never applyable.
- No git commands are run by Aegis Code.
