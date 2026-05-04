from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import yaml

from aegis_code.scaffolds import resolve_stack_profile


def _create_manifest(
    *,
    stack: str,
    stack_version: str,
    idea: str,
    test_command: str,
    created_files: list[str],
) -> str:
    safe_idea = idea.replace('"', "'")
    lines = [
        f"stack: {stack}",
        f"stack_version: \"{stack_version}\"",
        f"idea: \"{safe_idea}\"",
        f"test_command: \"{test_command}\"",
        "created_files:",
    ]
    for item in created_files:
        lines.append(f"  - {item}")
    lines.extend(
        [
            "scaffold_source: internal",
            "created_by: aegis-code",
        ]
    )
    return "\n".join(lines) + "\n"


_PROFILE_NAME_BY_STACK_ID = {
    "python-fastapi": "fastapi",
    "python-cli": "python-cli",
    "node-react": "node-react",
    "python-basic": "python-basic",
}


def _profile_dir() -> Path:
    return Path(__file__).resolve().parent / "scaffold_profiles"


def list_scaffold_profiles() -> list[str]:
    directory = _profile_dir()
    if not directory.exists():
        return []
    names = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".yml", ".yaml", ".json"}:
            continue
        names.append(path.stem)
    return names


def load_profile(profile_name: str) -> dict[str, Any]:
    directory = _profile_dir()
    candidates = [
        directory / f"{profile_name}.yml",
        directory / f"{profile_name}.yaml",
        directory / f"{profile_name}.json",
    ]
    source_path = next((path for path in candidates if path.exists()), None)
    if source_path is None:
        available = ", ".join(list_scaffold_profiles())
        raise ValueError(f"Missing scaffold profile '{profile_name}'. Available profiles: {available}")
    if source_path.suffix.lower() == ".json":
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    else:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid scaffold profile '{profile_name}': expected mapping")
    return raw


def load_external_profile(path: Path) -> dict[str, Any]:
    source_path = path.resolve()
    if not source_path.exists():
        raise ValueError(f"External scaffold profile not found: {path}")
    if source_path.suffix.lower() not in {".yml", ".yaml", ".json"}:
        raise ValueError("External scaffold profile must be YAML or JSON")
    try:
        if source_path.suffix.lower() == ".json":
            raw = json.loads(source_path.read_text(encoding="utf-8"))
        else:
            raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid external scaffold profile format: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("External scaffold profile must be a mapping")
    name = str(raw.get("name", "") or "").strip()
    files = raw.get("files", [])
    if not name:
        raise ValueError("External scaffold profile missing required field: name")
    if not isinstance(files, list):
        raise ValueError("External scaffold profile missing required field: files")
    normalized_files: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("External scaffold profile files must be objects with path/content")
        rel_path = str(item.get("path", "") or "").strip()
        content = str(item.get("content", "") or "")
        if not rel_path:
            raise ValueError("External scaffold profile file missing required field: path")
        normalized_files.append({"path": rel_path, "content": content})
    return {"name": name, "files": normalized_files}


def _resolve_profile_name(stack_id: str) -> str:
    return _PROFILE_NAME_BY_STACK_ID.get(stack_id, stack_id)


def _render_profile_files(profile: dict[str, Any], *, idea: str, test_command: str) -> dict[str, str]:
    files = profile.get("files", [])
    if not isinstance(files, list):
        raise ValueError("Invalid scaffold profile: files must be a list")
    rendered: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("path", "") or "").strip()
        content = str(item.get("content", "") or "")
        if not rel_path:
            continue
        rendered[rel_path] = (
            content.replace("{{idea}}", idea).replace("{{test_command}}", test_command)
        )
    return rendered


def _scaffold_files(stack_id: str, idea: str, test_command: str) -> dict[str, str]:
    _ = resolve_stack_profile(stack_id)
    profile = load_profile(_resolve_profile_name(stack_id))
    return _render_profile_files(profile, idea=idea, test_command=test_command)


def _is_windows_abs_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", value))


def _is_safe_target_relative_path(target: Path, rel_path: str) -> bool:
    raw = str(rel_path or "").strip()
    if not raw:
        return False
    if Path(raw).is_absolute() or _is_windows_abs_path(raw):
        return False
    resolved_target = target.resolve()
    resolved_candidate = (target / raw).resolve()
    try:
        resolved_candidate.relative_to(resolved_target)
    except Exception:
        return False
    return True


def create_scaffold(
    *,
    target: Path,
    cwd: Path,
    stack_id: str,
    stack_version: str,
    idea: str,
    test_command: str,
    confirm: bool,
    profile_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_cwd = cwd.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_cwd:
        return {"ok": False, "code": 2, "message": "Refusing scaffold: target must not be the current repository root."}

    if target.exists() and any(target.iterdir()):
        return {"ok": False, "code": 2, "message": "Refusing scaffold: target exists and is not empty."}

    if profile_override is not None:
        files = _render_profile_files(profile_override, idea=idea, test_command=test_command)
    else:
        files = _scaffold_files(stack_id=stack_id, idea=idea, test_command=test_command)
    for rel_path in files:
        if not _is_safe_target_relative_path(target, rel_path):
            return {"ok": False, "code": 2, "message": f"Refusing scaffold: unsafe file path: {rel_path}"}
    manifest_files = sorted(list(files.keys()) + [".aegis/create_manifest.yml"])
    manifest = _create_manifest(
        stack=stack_id,
        stack_version=stack_version,
        idea=idea,
        test_command=test_command,
        created_files=manifest_files,
    )
    files[".aegis/create_manifest.yml"] = manifest
    if not confirm:
        return {
            "ok": False,
            "code": 1,
            "message": "Scaffold preview only. Re-run with --confirm to write files.",
            "files": sorted(files.keys()),
            "target": str(target),
            "applied": False,
        }

    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rel_path, content in files.items():
        path = target / rel_path
        if path.exists():
            return {"ok": False, "code": 2, "message": f"Refusing scaffold: file already exists: {rel_path}"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel_path)
    return {
        "ok": True,
        "code": 0,
        "message": "Scaffold created.",
        "written": sorted(written),
        "target": str(target),
        "applied": True,
    }
