# Python API Reference

This document defines the stable public Python API for Aegis Code and how to use it safely from scripts, tools, and agents.

## Quickstart

Canonical programmatic workflow:

1. setup check
2. patch proposal
3. diff inspection
4. apply check
5. apply confirm
6. report access

```python
from aegis_code.api import AegisApiError, AegisCode, PatchOperation

client = AegisCode(project_path=".")
try:
    setup = client.setup_check()
    if not setup.initialized:
        print("Run `aegis-code setup` first, then configure provider access.")

    proposal = client.patch(
        task="add tests for save_note_to_file only",
        files=["tests/test_notes.py"],
        operation=PatchOperation.APPEND,
    )

    print("proposal:", proposal.status, proposal.diff_path)
    print(proposal.diff_text()[:200])
    print(proposal.inspect_diff().get("summary", {}))

    apply_check = proposal.apply(check=True)
    if apply_check.apply_blocked:
        print("blocked:", apply_check.errors)
    else:
        apply_result = proposal.apply(check=False)
        print("applied:", apply_result.applied)

    run_status = client.status()
    run_report = client.report()
    print("status:", run_status.run_status)
    print("report available:", run_report.available)
except AegisApiError as exc:
    print(f"Aegis API error: {exc}")
```

## End-to-End Example

The same flow using a mix of object-oriented and functional entry points:

```python
from pathlib import Path

from aegis_code.api import (
    AegisApiError,
    AegisCode,
    PatchOperation,
    report,
)

project = Path(".")
client = AegisCode(project_path=project)

try:
    setup = client.setup_check()
    if not setup.aegis_key:
        raise RuntimeError("Missing AEGIS_API_KEY for authenticated workflows.")

    proposal = client.patch(
        task="append one regression test for note save behavior",
        files=["tests/test_notes.py"],
        operation=PatchOperation.APPEND,
    )

    # Inspect proposal before mutation.
    _raw_diff = proposal.diff_text()
    inspection = proposal.inspect_diff()
    print("files in diff:", inspection.get("summary", {}).get("file_count", 0))

    # Safety check first.
    checked = proposal.apply(check=True)
    if checked.apply_blocked:
        print("Blocked:", checked.errors)
    else:
        applied = proposal.apply(check=False)
        print("Applied:", applied.applied, applied.files_changed)

    # Retrieve latest report with typed views.
    run_report = report(project_path=project)
    print("run:", run_report.summary.status)
    print("patch safety:", run_report.patch.safety)
    print("verification available:", run_report.verification.available)
    print("model:", run_report.model_selection.model)
    print("runtime mode:", run_report.runtime_control.mode)
    for action in run_report.next_actions:
        print(action.index, action.description)

except AegisApiError as exc:
    print("Aegis API failed:", exc)
```

## Public API Reference

### `AegisCode`

Public client class for one project path:

- `AegisCode(project_path=".")`
- `setup_check() -> SetupStatus`
- `patch(...) -> PatchProposal`
- `apply_patch(path=None, check=True) -> ApplyResult`
- `status() -> RunStatus`
- `report() -> RunReport`
- `latest_diff() -> Path | None`
- `latest_report_json() -> dict[str, Any] | None`
- `latest_report_markdown() -> str | None`

### Functional wrappers

All wrappers are exported from `aegis_code.api` and delegate to `AegisCode`:

- `setup_check(project_path=".")`
- `patch(..., project_path=".")`
- `apply_patch(path=None, check=True, project_path=".")`
- `status(project_path=".")`
- `report(project_path=".")`

### Return objects

Exported and stable:

- `SetupStatus`
- `PatchProposal`
- `ApplyResult`
- `RunStatus`
- `RunReport`

`PatchProposal` helpers:

- `diff_text(path=None) -> str`
- `inspect_diff(path=None) -> dict[str, Any]`
- `apply(check=True, path=None) -> ApplyResult`

## Exceptions Reference

Exported from `aegis_code.api`:

- `AegisApiError`: base exception for the public API.
- `AegisSetupError`: setup/readiness failures.
- `AegisPatchError`: patch proposal input/processing failures.
- `AegisApplyError`: apply/check failures.
- `AegisReportError`: report loading/parsing failures.

Guidance:

- Catch `AegisApiError` for broad integration-level error handling.
- Catch subclasses when retry/recovery behavior differs by operation.

## Operations Reference

Operation typing is exported as:

- `PatchOperation` enum
- `PatchOperationValue` literal type alias

Current supported values:

- `append`
- `create-file`
- `insert-after`
- `insert-before`
- `replace-block`
- `delete-block`
- `replace-file`
- `delete-file`
- `replace-symbol`
- `delete-symbol`
- `rename-file`
- `move-file`
- `batch`

## Typed Report Views

`RunReport` includes lightweight typed views over common sections while preserving raw access:

- `summary -> ReportSummary`
- `patch -> PatchSummary`
- `verification -> VerificationSummary`
- `model_selection -> ModelSelectionSummary`
- `runtime_control -> RuntimeControlSummary`
- `next_actions -> tuple[NextAction, ...]`
- `raw -> dict[str, Any] | None` (alias of `payload`)

Typed view classes:

- `ReportSummary`
- `PatchSummary`
- `VerificationSummary`
- `ModelSelectionSummary`
- `RuntimeControlSummary`
- `NextAction`

## Public vs Private Modules

Import from public entrypoint:

- `aegis_code.api`

Avoid importing internal modules directly for long-term compatibility:

- `aegis_code.runtime*`
- `aegis_code.runtime_components*`
- `aegis_code.providers*`
- `aegis_code.patches*`
- `aegis_code.scope*`
- `aegis_code.cli`

Internal modules may change without notice; wrappers in `aegis_code.api` are the compatibility layer.

## Stability Guarantees

Public stability contract:

- Names exported by `aegis_code.api.__all__` are the intended stable API surface.
- Public dataclass fields on exported API types are versioned for compatibility.
- Public exceptions and `PatchOperation` members are stable unless explicitly deprecated.

Forward-compatibility guidance for payloads:

- Use typed properties first (`RunReport.summary`, `RunReport.patch`, and others).
- Keep `.raw`/`.payload` access for fields not yet promoted to typed properties.
- Treat unknown keys in `.raw` as additive future metadata.
