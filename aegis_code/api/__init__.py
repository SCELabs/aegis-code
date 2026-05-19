"""Public Python API surface for Aegis Code."""

from __future__ import annotations

from pathlib import Path

from aegis_code.api.client import AegisCode
from aegis_code.api.errors import (
    AegisApiError,
    AegisApplyError,
    AegisPatchError,
    AegisReportError,
    AegisSetupError,
)
from aegis_code.api.operations import PatchOperation, PatchOperationValue
from aegis_code.api.types import (
    ApplyResult,
    ModelSelectionSummary,
    NextAction,
    PatchProposal,
    PatchSummary,
    ReportSummary,
    RunReport,
    RunStatus,
    RuntimeControlSummary,
    SetupStatus,
    VerificationSummary,
)

__all__ = [
    "AegisCode",
    "AegisApiError",
    "AegisSetupError",
    "AegisPatchError",
    "AegisApplyError",
    "AegisReportError",
    "PatchOperation",
    "PatchOperationValue",
    "SetupStatus",
    "PatchProposal",
    "ApplyResult",
    "ReportSummary",
    "PatchSummary",
    "VerificationSummary",
    "ModelSelectionSummary",
    "RuntimeControlSummary",
    "NextAction",
    "RunStatus",
    "RunReport",
    "setup_check",
    "patch",
    "apply_patch",
    "status",
    "report",
]


def setup_check(*, project_path: str | Path = ".") -> SetupStatus:
    return AegisCode(project_path=project_path).setup_check()


def patch(
    *,
    task: str,
    files: list[str],
    operation: PatchOperation | PatchOperationValue | str | None = None,
    allow_create: bool = False,
    max_files: int | None = None,
    target: str | None = None,
    anchor: str | None = None,
    symbol: str | None = None,
    budget: float | None = None,
    mode: str | None = None,
    dry_run: bool = False,
    analyze_failures: bool = True,
    session: str | None = None,
    no_report: bool = False,
    provider_timeout_seconds: int | None = None,
    project_path: str | Path = ".",
) -> PatchProposal:
    return AegisCode(project_path=project_path).patch(
        task=task,
        files=files,
        operation=operation,
        allow_create=allow_create,
        max_files=max_files,
        target=target,
        anchor=anchor,
        symbol=symbol,
        budget=budget,
        mode=mode,
        dry_run=dry_run,
        analyze_failures=analyze_failures,
        session=session,
        no_report=no_report,
        provider_timeout_seconds=provider_timeout_seconds,
    )


def apply_patch(*, path: str | Path | None = None, check: bool = True, project_path: str | Path = ".") -> ApplyResult:
    return AegisCode(project_path=project_path).apply_patch(path=path, check=check)


def status(*, project_path: str | Path = ".") -> RunStatus:
    return AegisCode(project_path=project_path).status()


def report(*, project_path: str | Path = ".") -> RunReport:
    return AegisCode(project_path=project_path).report()
