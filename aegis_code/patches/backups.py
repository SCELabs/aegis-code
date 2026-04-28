from __future__ import annotations

from pathlib import Path
from typing import Any


def _backups_root(cwd: Path | None = None) -> Path:
    root = cwd or Path.cwd()
    return root / ".aegis" / "backups"


def _is_safe_backup_id(backup_id: str) -> bool:
    if not backup_id or backup_id in {".", ".."}:
        return False
    if "/" in backup_id or "\\" in backup_id:
        return False
    if Path(backup_id).is_absolute():
        return False
    return True


def list_backups(cwd: Path | None = None) -> dict[str, Any]:
    root = _backups_root(cwd)
    if not root.exists():
        return {"backups": []}

    snapshots: list[dict[str, Any]] = []
    dirs = [p for p in root.iterdir() if p.is_dir()]
    for snap in sorted(dirs, key=lambda p: p.name, reverse=True):
        files: list[str] = []
        for file in sorted(snap.rglob("*")):
            if file.is_file():
                files.append(str(file.relative_to(snap)).replace("\\", "/"))
        snapshots.append({"id": snap.name, "files": files})
    return {"backups": snapshots}


def restore_backup(backup_id: str, cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    result: dict[str, Any] = {
        "restored": False,
        "backup_id": backup_id,
        "files": [],
        "errors": [],
    }
    if not _is_safe_backup_id(backup_id):
        result["errors"] = ["invalid_backup_id"]
        return result

    backup_dir = _backups_root(root) / backup_id
    if not backup_dir.exists() or not backup_dir.is_dir():
        result["errors"] = ["backup_not_found"]
        return result

    restored_files: list[str] = []
    for source in sorted(backup_dir.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(backup_dir)
        target = root / rel
        try:
            target.resolve().relative_to(root.resolve())
        except Exception:
            result["errors"] = ["restore_target_outside_cwd"]
            return result
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        restored_files.append(str(rel).replace("\\", "/"))

    result["restored"] = True
    result["files"] = restored_files
    return result

