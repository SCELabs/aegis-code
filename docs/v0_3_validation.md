# v0.3 Validation

## What v0.3 validates
- Initial safe test execution and failure observation.
- Failure parsing, context extraction, and optional SLL signal synthesis.
- Aegis-guided retry control with bounded `max_retries`.
- Proposal-only patch planning from final failure state.

## Smoke test
1. Run `python -m pytest -q`.
2. Run `aegis-code "validate controlled loop" --no-report` for a quick command-path check.

## Manual temporary failure check
1. Introduce a temporary failing assertion in an existing local test.
2. Run `aegis-code "validate retry behavior"`.
3. Remove the temporary failing assertion after validation.

## Expected report behavior
- `latest.md` shows:
  - Test Attempts
  - Synthesized Symptoms
  - Retry Policy
  - Final Failure State
  - Proposed Fix Plan
- `latest.json` preserves compatibility fields (`failures`, `failure_context`, `sll_analysis`, `patch_plan`, `aegis_execution`, `selected_model`, `status`).

## Safety guarantees
- No file edits are performed by runtime.
- No patch application occurs.
- Retries only rerun the configured safe test command.

