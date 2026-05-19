from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from aegis_code.budget import get_budget_state
from aegis_code.config import load_config, project_paths
from aegis_code.context_state import load_runtime_context
from aegis_code.policy import build_runtime_policy_payload, select_runtime_mode
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.scope import build_scope_contract_from_cli
from aegis_code.setup import check_setup

from aegis_code.api.types import ApplyResult, PatchProposal, RunReport, RunStatus, SetupStatus


class AegisCode:
    """Small programmatic API for the canonical Aegis Code workflow."""

    def __init__(self, project_path: str | Path = ".") -> None:
        self.project_path = Path(project_path).resolve()

    def setup_check(self) -> SetupStatus:
        return SetupStatus.from_dict(check_setup(self.project_path))

    def patch(
        self,
        *,
        task: str,
        files: list[str],
        operation: str | None = None,
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
    ) -> PatchProposal:
        if not str(task or "").strip():
            raise ValueError("task is required")
        if not files:
            raise ValueError("files is required; pass at least one path")

        cfg = load_config(self.project_path)
        base_mode = mode or cfg.mode
        final_mode = select_runtime_mode(base_mode, cwd=self.project_path)
        scope_contract = build_scope_contract_from_cli(
            files=[str(item) for item in files],
            allow_create=bool(allow_create),
            max_files=max_files,
            cwd=self.project_path,
            operation=operation,
            destination_path=target,
            anchor=anchor,
            symbol=symbol,
        )

        payload = run_task(
            options=TaskOptions(
                task=task,
                budget=budget,
                mode=final_mode,
                dry_run=dry_run,
                analyze_failures=analyze_failures,
                propose_patch=True,
                session=session,
                no_report=no_report,
                project_context=load_runtime_context(cwd=self.project_path),
                budget_state=get_budget_state(cwd=self.project_path),
                runtime_policy=build_runtime_policy_payload(base_mode, final_mode, cwd=self.project_path),
                provider_timeout_seconds=provider_timeout_seconds,
                command="patch",
                scope_contract=asdict(scope_contract),
                patch_operation=operation,
                destination_path=target,
                anchor=anchor,
                symbol=symbol,
            ),
            cwd=self.project_path,
        )
        patch_diff = payload.get("patch_diff", {}) if isinstance(payload.get("patch_diff"), dict) else {}
        patch_operation = payload.get("patch_operation", {}) if isinstance(payload.get("patch_operation"), dict) else {}
        diff_path_text = patch_diff.get("path")
        diff_path: Path | None = None
        if isinstance(diff_path_text, str) and diff_path_text.strip():
            raw_path = Path(diff_path_text)
            diff_path = raw_path if raw_path.is_absolute() else (self.project_path / raw_path)
        operation_name = patch_operation.get("operation")
        return PatchProposal(
            status=str(patch_diff.get("status", "unknown")),
            diff_path=diff_path,
            error=str(patch_diff.get("error")) if patch_diff.get("error") is not None else None,
            operation=str(operation_name) if operation_name is not None else None,
            payload=payload,
            project_path=self.project_path,
        )

    def apply_patch(self, *, path: str | Path | None = None, check: bool = True) -> ApplyResult:
        if path is None:
            target = project_paths(self.project_path)["latest_diff"]
        else:
            raw = Path(path)
            target = raw.resolve() if raw.is_absolute() else (self.project_path / raw)
        proposal = PatchProposal(
            status="generated",
            diff_path=target,
            error=None,
            operation=None,
            payload={},
            project_path=self.project_path,
        )
        return proposal.apply(check=check)

    def status(self) -> RunStatus:
        latest_json = project_paths(self.project_path)["latest_json"]
        if not latest_json.exists():
            return RunStatus(available=False, task=None, run_status=None, failure_count=0, payload=None)
        payload: dict[str, Any] | None = None
        try:
            loaded = json.loads(latest_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = None
        if payload is None:
            return RunStatus(available=False, task=None, run_status=None, failure_count=0, payload=None)
        failures = payload.get("failures", {}) if isinstance(payload.get("failures"), dict) else {}
        return RunStatus(
            available=True,
            task=str(payload.get("task")) if payload.get("task") is not None else None,
            run_status=str(payload.get("status")) if payload.get("status") is not None else None,
            failure_count=int(failures.get("failure_count", 0) or 0),
            payload=payload,
        )

    def report(self) -> RunReport:
        return RunReport.load(self.project_path)
