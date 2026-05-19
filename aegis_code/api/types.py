from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths
from aegis_code.patches.apply_check import check_patch_file
from aegis_code.patches.patch_applier import apply_patch_file
from aegis_code.report import read_latest_markdown


@dataclass(frozen=True, slots=True)
class SetupStatus:
    initialized: bool
    aegis_key: bool
    provider_key: bool
    provider_preset: bool
    context_available: bool
    latest_run: bool
    verification_available: bool
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SetupStatus":
        return cls(
            initialized=bool(data.get("initialized", False)),
            aegis_key=bool(data.get("aegis_key", False)),
            provider_key=bool(data.get("provider_key", False)),
            provider_preset=bool(data.get("provider_preset", False)),
            context_available=bool(data.get("context_available", False)),
            latest_run=bool(data.get("latest_run", False)),
            verification_available=bool(data.get("verification_available", False)),
            raw=dict(data),
        )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    applied: bool
    valid: bool | None
    apply_blocked: bool | None
    path: str | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    files_changed: tuple[str, ...]
    raw: dict[str, Any]

    @classmethod
    def from_check_result(cls, data: dict[str, Any]) -> "ApplyResult":
        return cls(
            applied=False,
            valid=bool(data.get("valid", False)),
            apply_blocked=bool(data.get("apply_blocked", False)),
            path=str(data.get("path")) if data.get("path") is not None else None,
            warnings=tuple(str(item) for item in data.get("warnings", []) if item is not None),
            errors=tuple(str(item) for item in data.get("errors", []) if item is not None),
            files_changed=tuple(),
            raw=dict(data),
        )

    @classmethod
    def from_apply_result(cls, data: dict[str, Any]) -> "ApplyResult":
        changed: list[str] = []
        for item in data.get("files_changed", []):
            if isinstance(item, dict) and item.get("path") is not None:
                changed.append(str(item.get("path")))
        return cls(
            applied=bool(data.get("applied", False)),
            valid=None,
            apply_blocked=None,
            path=str(data.get("path")) if data.get("path") is not None else None,
            warnings=tuple(str(item) for item in data.get("warnings", []) if item is not None),
            errors=tuple(str(item) for item in data.get("errors", []) if item is not None),
            files_changed=tuple(changed),
            raw=dict(data),
        )


@dataclass(frozen=True, slots=True)
class PatchProposal:
    status: str
    diff_path: Path | None
    error: str | None
    operation: str | None
    payload: dict[str, Any]
    project_path: Path

    def apply(self, *, check: bool = True, path: str | Path | None = None) -> ApplyResult:
        if path is None:
            target = self.diff_path
        else:
            raw = Path(path)
            target = raw if raw.is_absolute() else (self.project_path / raw)
        if target is None:
            return ApplyResult(
                applied=False,
                valid=False if check else None,
                apply_blocked=True if check else None,
                path=None,
                warnings=tuple(),
                errors=("diff_path_missing",),
                files_changed=tuple(),
                raw={"errors": ["diff_path_missing"]},
            )
        if check:
            checked = check_patch_file(target, cwd=self.project_path)
            return ApplyResult.from_check_result(checked)
        applied = apply_patch_file(target, cwd=self.project_path)
        return ApplyResult.from_apply_result(applied)


@dataclass(frozen=True, slots=True)
class RunStatus:
    available: bool
    task: str | None
    run_status: str | None
    failure_count: int
    payload: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class RunReport:
    available: bool
    markdown_path: Path | None
    markdown: str | None
    json_path: Path | None
    payload: dict[str, Any] | None

    @classmethod
    def load(cls, project_path: Path) -> "RunReport":
        latest_markdown = read_latest_markdown(project_path)
        markdown_path: Path | None = None
        markdown: str | None = None
        if latest_markdown is not None:
            markdown_path, markdown = latest_markdown
        json_path = project_paths(project_path)["latest_json"]
        payload: dict[str, Any] | None = None
        if json_path.exists():
            try:
                loaded = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except Exception:
                payload = None
        return cls(
            available=bool(markdown_path is not None or payload is not None),
            markdown_path=markdown_path,
            markdown=markdown,
            json_path=json_path if json_path.exists() else None,
            payload=payload,
        )
