# Runtime Modularization RFC (No-Behavior-Change Plan)

## Summary
`aegis_code/runtime.py` currently combines orchestration, policy, prompt shaping inputs, diff validation/safety, append-specific execution, feature-step execution, diagnostics, and payload assembly. This RFC proposes a phased modular refactor that preserves current behavior and public CLI/runtime contracts while reducing coupling and regression risk.

This document is intentionally scoped to design and extraction sequencing only. No runtime behavior changes are proposed in this RFC.

## Goals
- Prevent `runtime.py` from becoming a long-term god module.
- Improve maintainability and testability by isolating cohesive logic groups.
- Keep existing external behavior unchanged:
  - CLI behavior and output schema
  - Runtime status semantics
  - Patch-generation and guardrail outcomes
  - Existing test expectations and monkeypatch paths (for Phase 1 compatibility)

## Non-Goals
- No policy rewrites.
- No routing/control-flow changes in Phase 1.
- No feature additions.
- No payload schema changes.

## Current Pain Points
- High cognitive load: one file owns classification, execution, diff repair, safety checks, and reporting payload shaping.
- Tight coupling: helper functions depend on implicit shared state and adjacent helpers in the same module.
- Fragile testing surface: many tests monkeypatch `aegis_code.runtime.*` internals; moving logic without compatibility shims can cause broad breakage.
- Mixed abstraction levels: pure string/path utilities are interleaved with provider orchestration and retry control.
- Difficult ownership boundaries: append mode, feature-plan mode, and validation pipelines are all in one execution function.

## Cohesive Logic Groups To Extract
The following groups are present and should become dedicated modules:

1. Task classification
- intent detection and task-type classification helpers.

2. Append execution and validation
- append prompt context shaping inputs, provider append JSON parsing, append diff build/validation.

3. Feature plan construction
- feature-step plan synthesis from task/scope constraints.

4. Feature-step execution
- per-step controller invocation, accumulation, and failure roll-up.

5. Source-truth guards
- repository/snippet-alignment checks to block invented assumptions.

6. JS grounding/context extraction
- `package.json type`, import style inference, `node:test` vs jest-like signals.

7. Semantic policy guards
- destructive rewrite checks, hard-invalid decisions, prioritized patch errors.

8. Plan consistency
- allowed-target and proposed-target consistency checks.

9. Diff pipeline/report payload shaping
- patch-diff default object, apply safety computation, touched-file extraction, payload assembly helpers.

10. Verification/baseline diagnostics
- verification command selection integration, command-attempt diagnostics shaping.

## Proposed Target Module Map
Proposed files under `aegis_code/runtime_components/`:

- `aegis_code/runtime_components/__init__.py`
- `aegis_code/runtime_components/task_classification.py`
  - `is_constructive_task`, `classify_task_type`, related intent helpers.
- `aegis_code/runtime_components/append_context.py`
  - append target context extraction, JS context extraction helpers.
- `aegis_code/runtime_components/append_pipeline.py`
  - append response parsing, append diff build/validation, append sanity checks.
- `aegis_code/runtime_components/source_truth_guards.py`
  - source conflict detection and repo/snippet truth checks.
- `aegis_code/runtime_components/semantic_guards.py`
  - destructive rewrite detection, error prioritization, content guard predicates.
- `aegis_code/runtime_components/feature_plan.py`
  - feature plan construction.
- `aegis_code/runtime_components/feature_step_executor.py`
  - multi-step execution and aggregation helpers.
- `aegis_code/runtime_components/plan_consistency.py`
  - normalize paths, collect targets, compute plan consistency.
- `aegis_code/runtime_components/diff_pipeline.py`
  - diff parsing/hunk application/syntax check helpers.
- `aegis_code/runtime_components/payload.py`
  - payload shaping helpers for verification diagnostics/apply-safety/touched files.
- `aegis_code/runtime_components/verification_diagnostics.py`
  - baseline verification/diagnostic shaping utilities used by runtime orchestration.

Note: existing modules such as `aegis_code/verification.py`, `aegis_code/providers/base.py`, and `aegis_code/patches/*` remain source-of-truth where already established.

## Phased Refactor Plan

### Phase 1 (Low Risk, Extraction Only)
Constraints:
- Move pure helper functions only.
- No orchestration routing changes in `build_run_payload`.
- No behavior changes.
- Keep public CLI behavior unchanged.
- Preserve monkeypatch compatibility by re-exporting wrappers in `runtime.py`.

Candidate functions for Phase 1 extraction:
- Task classification helpers.
- Path normalization/target collection/plan-consistency helpers.
- Additive/destructive rewrite predicates.
- Append parse/validation helpers that are pure.
- Payload helper utilities (`_collect_changed_files`, `_collect_repo_file_candidates`, apply-safety calc helpers).

Implementation style:
1. Copy helper bodies into new module.
2. In `runtime.py`, keep same function names but delegate to new module functions.
3. Maintain signatures and return shapes exactly.
4. Keep import graph acyclic (components should not import `runtime.py`).

### Phase 2 (Still Behavior-Preserving, Controlled Wiring)
- Extract append execution block into `append_pipeline.py` functions returning the same structures currently consumed by `build_run_payload`.
- Extract feature-step execution loop into `feature_step_executor.py`.
- Keep top-level flow in `build_run_payload`; call extracted functions.

### Phase 3 (Orchestration Decomposition)
- Split `build_run_payload` into sub-orchestrators:
  - verification/retry stage
  - patch-plan stage
  - provider/patch stage
  - final payload/report shaping stage
- Retain `build_run_payload` as stable façade.

### Phase 4 (Optional Future Cleanup)
- Introduce typed dataclasses for internal stage outputs (not external payload schema).
- Reduce mutation-heavy dict updates where feasible while keeping output identical.

## Extraction Order (Recommended)
1. `task_classification.py`
2. `plan_consistency.py`
3. `semantic_guards.py` (error prioritization + destructive rewrite predicates)
4. `append_context.py` (including JS grounding extraction)
5. `append_pipeline.py` pure helpers
6. `payload.py` utility helpers
7. `feature_plan.py`
8. `feature_step_executor.py`
9. `diff_pipeline.py` utilities

Rationale:
- Start with pure, low-dependency helpers that are easiest to verify.
- Defer heavy orchestration extraction until helper seams are stable.

## Regression Test Strategy
Phase 1 should rely on existing tests and add only narrowly scoped extraction-guard tests if needed.

Primary suites to run after each extraction slice:
- `tests/test_runtime.py`
- `tests/test_provider_patch_diff.py`
- `tests/test_report.py`
- `tests/test_verification.py`
- `tests/test_constraints.py`
- `tests/test_task_context.py`
- `tests/test_cli.py` (spot checks for CLI output contract)

Compatibility strategy for monkeypatch-heavy tests:
- Keep `runtime.py` wrapper function names intact in Phase 1.
- Avoid direct external imports of new component functions from tests until Phase 2+.
- If wrappers are later removed, do so in a dedicated compatibility-breaking PR with explicit migration notes.

## Risks
- Hidden behavior drift from subtle normalization/order differences.
- Monkeypatch path instability due to function relocation.
- Circular imports if extracted modules pull orchestration symbols.
- Payload key ordering/shape drift causing report and CLI expectation failures.

## Mitigations
- Wrapper/delegation pattern in `runtime.py` during Phase 1.
- Snapshot checks for key payload fields before/after extraction.
- Strict “no conditional logic changes” rule in Phase 1 PR template.
- Small extraction PRs (one logic group at a time) with focused test runs.

## Rollback Plan
- Keep each extraction as an isolated commit or PR slice.
- If regression appears, revert only the affected extraction slice and retain prior slices.
- Because behavior is unchanged and wrappers remain, rollback should be straightforward:
  - restore old helper body in `runtime.py`
  - remove or ignore extracted module function

## Acceptance Criteria (Phase 1)
- `build_run_payload` and `run_task` externally behave identically.
- CLI behavior and output schema unchanged.
- Existing runtime/provider/report/verification tests remain green.
- `runtime.py` line count and helper density decrease meaningfully without control-flow changes.

## Notes on Existing Adjacent Modules
- `aegis_code/verification.py` already encapsulates verification command resolution and should remain canonical.
- `aegis_code/providers/base.py` already centralizes prompt construction constraints and should continue to receive grounded context from runtime.
- `aegis_code/patches/*` modules remain canonical for diff inspection/repair/policy primitives; extraction should compose these rather than duplicate logic.

