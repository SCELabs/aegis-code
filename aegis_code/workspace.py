from __future__ import annotations

import json
from pathlib import Path

from aegis_code.budget import can_spend, get_budget_state, load_budget, record_event
from aegis_code.config import load_config, project_paths
from aegis_code.context_state import refresh_context
from aegis_code.context_state import load_runtime_context
from aegis_code.policy import build_runtime_policy_payload, get_mode_reason, select_runtime_mode
from aegis_code.runtime import TaskOptions, run_task


def _workspace_path(cwd: Path) -> Path:
    return project_paths(cwd)["workspace_path"]


def _default_workspace() -> dict:
    return {"version": "0.1", "projects": []}


def load_workspace(cwd: Path) -> dict | None:
    path = _workspace_path(cwd)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _default_workspace()
    projects = data.get("projects")
    if not isinstance(projects, list):
        return _default_workspace()
    version = str(data.get("version", "0.1"))
    return {"version": version, "projects": projects}


def save_workspace(data: dict, cwd: Path) -> None:
    path = _workspace_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def init_workspace(cwd: Path) -> dict:
    path = _workspace_path(cwd)
    created = not path.exists()
    if created:
        save_workspace(_default_workspace(), cwd)
    return {"created": created, "path": str(path)}


def add_project(path: Path, cwd: Path) -> dict:
    if not path.exists() or not path.is_dir():
        return {"added": False, "reason": "path does not exist"}
    project_path = path.resolve()

    existing = load_workspace(cwd)
    if existing is None:
        init_workspace(cwd)
        existing = load_workspace(cwd) or _default_workspace()

    projects = existing.get("projects", [])
    for item in projects:
        if not isinstance(item, dict):
            continue
        current = item.get("path")
        if isinstance(current, str) and Path(current).resolve() == project_path:
            return {"added": False, "reason": "already exists"}

    projects.append({"path": str(project_path), "name": project_path.name})
    save_workspace({"version": str(existing.get("version", "0.1")), "projects": projects}, cwd)
    return {"added": True}


def remove_project(path: Path, cwd: Path) -> dict:
    existing = load_workspace(cwd)
    if existing is None:
        return {"removed": False, "reason": "no_workspace"}

    project_path = path.resolve()
    projects = existing.get("projects", [])
    updated_projects = []
    removed = False

    for item in projects:
        if not isinstance(item, dict):
            updated_projects.append(item)
            continue
        current = item.get("path")
        if (
            not removed
            and isinstance(current, str)
            and Path(current).resolve() == project_path
        ):
            removed = True
            continue
        updated_projects.append(item)

    if not removed:
        return {"removed": False, "reason": "not_found"}

    save_workspace({"version": str(existing.get("version", "0.1")), "projects": updated_projects}, cwd)
    return {"removed": True, "path": str(project_path)}


def get_status(cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    formatted = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        name = str(item.get("name", Path(path).name if path else ""))
        exists = Path(path).exists() if path else False
        formatted.append({"path": path, "name": name, "exists": exists})

    return {"exists": True, "project_count": len(formatted), "projects": formatted}


def get_detailed_status(cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    formatted = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        name = str(item.get("name", Path(path).name if path else ""))
        project_path = Path(path) if path else None
        exists = project_path.exists() if project_path else False
        if not exists:
            formatted.append(
                {
                    "name": name,
                    "path": path,
                    "exists": False,
                    "config": False,
                    "budget": False,
                    "context": False,
                    "latest_run": False,
                    "mode": "unknown",
                }
            )
            continue

        config_path = project_path / ".aegis" / "aegis-code.yml"
        budget_path = project_path / ".aegis" / "budget.json"
        context_path = project_path / ".aegis" / "context"
        latest_run_path = project_path / ".aegis" / "runs" / "latest.json"
        config_exists = config_path.exists()
        mode = load_config(project_path).mode if config_exists else "unknown"
        formatted.append(
            {
                "name": name,
                "path": path,
                "exists": True,
                "config": config_exists,
                "budget": budget_path.exists(),
                "context": context_path.exists(),
                "latest_run": latest_run_path.exists(),
                "mode": mode,
            }
        )

    return {"exists": True, "project_count": len(formatted), "projects": formatted}


def get_workspace_overview(cwd: Path) -> dict:
    status = get_detailed_status(cwd)
    if not status.get("exists", False):
        return {"exists": False}

    projects = status.get("projects", [])
    total = len(projects)
    available = sum(1 for item in projects if bool(item.get("exists", False)))
    missing = sum(1 for item in projects if not bool(item.get("exists", False)))
    configured = sum(1 for item in projects if bool(item.get("config", False)))
    budget = sum(1 for item in projects if bool(item.get("budget", False)))
    context = sum(1 for item in projects if bool(item.get("context", False)))
    latest_run = sum(1 for item in projects if bool(item.get("latest_run", False)))

    return {
        "exists": True,
        "total": total,
        "available": available,
        "missing": missing,
        "configured": configured,
        "budget": budget,
        "context": context,
        "latest_run": latest_run,
    }


def refresh_workspace_context(cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    total = 0
    refreshed = 0
    skipped_missing = 0
    for item in projects:
        if not isinstance(item, dict):
            continue
        total += 1
        path = str(item.get("path", ""))
        project_path = Path(path) if path else None
        if project_path is None or not project_path.exists():
            skipped_missing += 1
            continue
        refresh_context(cwd=project_path)
        refreshed += 1

    return {
        "exists": True,
        "total": total,
        "refreshed": refreshed,
        "skipped_missing": skipped_missing,
    }


def preview_workspace_run(task: str, cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    total = 0
    would_run = 0
    skipped_missing = 0
    preview_projects = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        total += 1
        path = str(item.get("path", ""))
        name = str(item.get("name", Path(path).name if path else ""))
        project_path = Path(path) if path else None
        if project_path is None or not project_path.exists():
            skipped_missing += 1
            continue
        would_run += 1
        preview_projects.append({"name": name, "path": path, "action": "would_run"})

    return {
        "exists": True,
        "task": task,
        "total": total,
        "would_run": would_run,
        "skipped_missing": skipped_missing,
        "projects": preview_projects,
    }


def _allow_runtime_for_workspace(
    cwd: Path,
    operation: str = "run_task",
    estimated_cost: float = 0.01,
    selected_mode: str | None = None,
    reason: str | None = None,
) -> bool:
    budget = load_budget(cwd)
    if not budget:
        return True
    if not can_spend(operation, estimated_cost, cwd):
        return False
    record_event(operation, estimated_cost, cwd, selected_mode=selected_mode, reason=reason)
    return True


def run_workspace_task(task: str, cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    executed = 0
    skipped_missing = 0
    skipped_budget = 0
    results = []

    for item in projects:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        name = str(item.get("name", Path(path).name if path else ""))
        project_path = Path(path) if path else None
        if project_path is None or not project_path.exists():
            skipped_missing += 1
            continue

        cfg = load_config(project_path)
        base_mode = cfg.mode
        final_mode = select_runtime_mode(base_mode, cwd=project_path)
        reason = get_mode_reason(base_mode, final_mode, cwd=project_path)

        if not _allow_runtime_for_workspace(project_path, selected_mode=final_mode, reason=reason):
            skipped_budget += 1
            continue

        project_context = load_runtime_context(cwd=project_path)
        budget_state = get_budget_state(cwd=project_path)
        runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=project_path)

        options = TaskOptions(
            task=task,
            mode=final_mode,
            project_context=project_context,
            budget_state=budget_state,
            runtime_policy=runtime_policy,
        )
        payload = run_task(options=options, cwd=project_path)
        executed += 1
        results.append(
            {
                "name": name,
                "path": path,
                "status": payload.get("status"),
                "mode": final_mode,
            }
        )

    return {
        "exists": True,
        "task": task,
        "executed": executed,
        "skipped_missing": skipped_missing,
        "skipped_budget": skipped_budget,
        "projects": results,
    }
