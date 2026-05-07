# Multi-File Feature Execution RFC (Phase 1)

## 1. Problem Statement

Aegis Code is strong at bounded, controlled patch generation, but multi-file feature work is still treated mostly as a single-shot patch generation problem. When a feature legitimately spans multiple files (for example source + tests + docs), a single generation pass is more likely to fail plan consistency, scope checks, or output validity.

The goal of Phase 1 is to support reliable multi-file feature execution while preserving Aegis Code's control model and avoiding autonomous loop behavior.

## 2. Current Patch Pipeline Summary

This summarizes the current flow at a high level:

1. CLI `patch` command requires explicit `--file` scope and builds a scope contract.
2. Runtime (`build_run_payload`) builds context (repo map, relevant snippets, failure/task context) and patch plan.
3. Runtime attempts structured proposal generation first (non-docs, non-append).
4. Structured proposal controller validates paths/operations/files through `ProposalContract` and structured edit conversion.
5. Runtime may use unified-diff fallback when structured generation is unavailable/skipped.
6. Runtime runs validation, optional repair paths, plan consistency, syntax/safety checks, and writes either accepted or invalid diff artifacts.

Key characteristics of the current system:

- Strong explicit scope contract support.
- Controlled mutation model (`apply --confirm` required).
- Bounded retry behavior.
- Single pass proposal acceptance for most multi-file work.

## 3. Why Single-Shot Multi-File Patching Fails

Single-shot multi-file generation fails more often because:

- Multiple file intents must be satisfied in one output, increasing schema/format and planning errors.
- Plan consistency currently expects planned targets in the final diff, so partial progress is often treated as failure.
- Structured retry depth is intentionally shallow and not step-aware.
- Unified fallback can reduce contract fidelity for complex feature edits.
- Multi-file semantic coupling (source + tests + docs) is hard to satisfy in one bounded response.

The issue is not lack of controls; it is lack of a bounded, deterministic step model inside the existing controls.

## 4. Product Principle

Developer controls scope, Aegis controls mutation, LLM generates bounded content.

Interpretation for Phase 1:

- Developer decides explicit file scope and operation expectations.
- Aegis enforces path/operation/safety/validation constraints at each stage.
- LLM output remains proposal-only and constrained to bounded per-step requests.
- No autonomous planning loop beyond strict deterministic limits.

## 5. Proposed Phase 1 Architecture

### 5.1 `feature_plan`

Introduce a runtime-level `feature_plan` artifact (diagnostic/report payload only in Phase 1) derived from:

- explicit scope contract (`allowed_targets`, `allowed_operations`, `max_files`)
- patch plan proposed changes
- task type hints

`feature_plan` includes ordered `steps`, each containing:

- `step_id`
- `target_file`
- `operation` (`create`, `replace`, or `append`)
- `intent`
- optional bounded constraints (for example `max_changed_lines`, symbol hints)

### 5.2 Ordered Feature Steps

Use deterministic ordering:

1. explicit `--file` order when available
2. then normalized path lexical order for any remaining inferred items

Bounded limits:

- cap on total step count
- cap on files touched
- cap on total added/changed lines

### 5.3 Per-Step Contracts

For each step, derive a narrowed contract from existing `ProposalContract` fields:

- single allowed target for that step
- step-specific allowed operation
- inherited safety restrictions (no delete/rename unless ever explicitly allowed in future phases)
- inherited new-file policy from scope

This keeps each generation request small and auditable.

### 5.4 Per-Step Validation

After each step proposal:

- validate structured output and path canonicalization
- validate operation mode against step contract
- run existing syntax/safety guards relevant to touched content
- reject step on hard invalid reasons

At most one correction retry per step.

### 5.5 Accumulated Candidate Diff

Accepted step diffs are accumulated into a single candidate artifact for the run.

- accumulation is deterministic and bounded
- no file application occurs
- candidate remains proposal-only

### 5.6 Final Validation

After all required steps complete:

- run existing diff validation and apply-check style checks on the accumulated candidate
- run plan consistency against required step targets
- run existing destructive rewrite and content safety protections
- emit final accepted/invalid/blocked status using existing reporting surfaces

### 5.7 Stop Conditions

Stop immediately when any of the following occurs:

- step contract violation (outside allowed targets/unsupported operation)
- hard invalid or unsafe content at step level
- bounded retry exhausted for a step
- step/file/size budget exceeded
- repeated same failure reason for the same step after retry

Stop behavior is fail-closed: no accepted diff is produced if required steps are not completed.

## 6. Non-Goals

Phase 1 explicitly does not include:

- autonomous agent loops
- automatic patch apply
- unbounded retries or self-directed expansion
- inferred broad scope beyond explicit developer constraints
- semantic retrieval/embedding/vector-db systems
- changing append routing semantics

## 7. Minimal Implementation Plan

1. Add `feature_plan` construction in runtime patch flow (metadata only, deterministic).
2. Add a bounded step executor that reuses existing structured proposal machinery with step-narrowed contracts.
3. Add deterministic diff accumulation for accepted steps.
4. Run current final validation pipeline against accumulated candidate.
5. Surface step diagnostics in report payload for blocked/failure states.
6. Keep fallback behavior bounded and contract-respecting (only when structured is unavailable, not when contract-violating).

Implementation constraints:

- preserve existing patch/apply safety model
- preserve append behavior
- preserve docs wrapped fallback behavior
- preserve destructive protections

## 8. Test Plan

### 8.1 Planning Tests

- deterministic `feature_plan` ordering from explicit scope
- step cap enforcement
- size budget metadata enforcement paths

### 8.2 Execution Tests

- 2-3 file feature task succeeds when each step is valid
- single-step failure blocks final output with step-specific diagnostics
- one retry per step max

### 8.3 Validation and Safety Tests

- final plan consistency succeeds when all required step targets present
- partial completion fails as blocked/invalid with missing step targets
- existing destructive/safety checks still trigger unchanged

### 8.4 Routing Regression Tests

- append flow unchanged
- docs wrapped fallback unchanged
- single-file patch behavior unchanged
- failure-repair path behavior unchanged

## 9. Open Questions

1. Should Phase 1 require every explicit scoped file to receive a step, or allow explicitly scoped context-only files?
2. Should per-step fallback to unified diff be allowed in all task types, or only selected ones?
3. Should final plan consistency map to step completion only, or both step completion and patch-plan proposed targets?
4. How should confidence scoring be aggregated across multiple accepted steps?
5. Should reports include per-step previews by default, or only in debug/blocked modes?
6. What is the best default max step count for Phase 1 (for example 3 vs 5)?
7. Should docs-only scoped tasks continue using current docs wrapper path before or after step accumulation?

---

Status: Draft RFC for Phase 1 design only. No runtime behavior change is introduced by this document.
