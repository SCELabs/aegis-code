# Operations Architecture (Controlled Mutations)

## Purpose
Define a clear operation model for mutation proposals where intent is explicit, enforcement is deterministic, and execution remains bounded.

## Mutation Philosophy
1. Developer/agent declares mutation intent: scope and operation.
2. Aegis enforces contract constraints before and after generation.
3. Provider proposes changes inside the contract boundary.
4. Verification (tests + validation + safety checks) determines readiness.

This keeps Aegis Code proposal-first and control-first: no silent operation selection, no implicit broad edits.

## Operation Set
Current:
- `append`

Planned:
- `create-file`
- `insert-after`
- `insert-before`
- `replace-block`
- `delete-block`
- `replace-file`

Notes:
- `append` remains explicit (`--operation append`).
- Planned operations are design targets only; this doc does not introduce new CLI behavior.

## Operation Contract Fields
Every operation request should normalize into one contract object with:
- `operation`: operation name.
- `target_file`: normalized repo-relative file path.
- `anchor`: textual or structural anchor (line marker, heading, pattern) when required.
- `symbol`: optional symbol/function/class anchor for structured insertion/replacement.
- `allow_deletions`: boolean guard (default false for additive operations).
- `allow_new_file`: boolean guard for creation semantics.
- `max_changed_lines`: hard budget for mutation size.

Recommended existing companion fields:
- allowed targets/files
- allowed operations
- max files
- missing targets / block reason

## Module Boundaries
- `aegis_code/cli.py`: parse user intent only (task, scope flags, operation flags).
- `aegis_code/scope/contract.py`: owns scope and contract normalization/validation.
- `aegis_code/operations/` (planned): owns operation execution semantics and operation-specific validators.
- `aegis_code/providers/prompts/` (planned): owns operation-specific prompt templates/instructions.
- `aegis_code/runtime.py`: orchestration only (routing, policy checks, verification/report assembly), not operation business logic.

Boundary rule:
- Runtime should consume contracts and operation results, not encode operation semantics inline.

## Error Code Model
Operation failures should be explicit, stable, and user-actionable.

Shape:
- `operation_<operation>_<reason>`
- Keep existing stable codes where already in use (for backward compatibility), especially append codes.

Existing append-specific examples:
- `append_output_invalid`
- `append_syntax_invalid`
- `append_semantic_suspicious`
- `invalid_append_operation`
- `append_source_conflict`
- `no_append_needed`

Proposed generic families:
- `operation_contract_invalid`
- `operation_target_missing`
- `operation_anchor_not_found`
- `operation_symbol_not_found`
- `operation_budget_exceeded`
- `operation_validation_failed`
- `operation_policy_blocked`

Rule:
- Do not collapse operation-specific failures into generic skip reasons when operation flow was actually attempted.

## Agent Usage Examples
Explicit append:
```bash
aegis-code patch --file tests/test_cli.py --operation append "add regression test for invalid todo id"
```

Planned insert-after shape (future):
```text
operation=insert-after
target_file=src/notes.js
symbol=addNote
max_changed_lines=40
allow_deletions=false
```

Planned replace-block shape (future):
```text
operation=replace-block
target_file=README.md
anchor="## Usage"
max_changed_lines=80
allow_deletions=true
```

## Phased Roadmap
1. Contract hardening
- Normalize operation contract fields in one place.
- Enforce explicit operation intent with no silent inference.

2. Operation module extraction
- Move append and future operation semantics into `operations/`.
- Keep runtime orchestration stable.

3. Prompt specialization
- Add operation-specific provider prompt modules under `providers/prompts/`.
- Keep operation constraints mirrored in post-generation validators.

4. Planned operation rollout
- Introduce one operation at a time with validator + policy + report support.
- Add regression tests for routing, enforcement, and error-code propagation.

5. Consistency and observability
- Ensure reports always surface operation name, source, and exact operation failure code.
- Preserve stable error-code contracts across releases.

