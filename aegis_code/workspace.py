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
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_workspace()
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


def compare_workspace_runs(cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    project_count = 0
    total_runs = 0
    missing_runs = 0
    skipped_missing = 0
    passed = 0
    failed = 0
    aegis_mode = 0
    local_mode = 0

    for item in projects:
        if not isinstance(item, dict):
            continue
        project_count += 1
        path = str(item.get("path", ""))
        project_path = Path(path) if path else None
        if project_path is None or not project_path.exists():
            skipped_missing += 1
            continue

        latest_run = project_path / ".aegis" / "runs" / "latest.json"
        if not latest_run.exists():
            missing_runs += 1
            continue

        try:
            payload = json.loads(latest_run.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        total_runs += 1
        if _is_run_passed(payload):
            passed += 1
        else:
            failed += 1

        runtime_adapter = payload.get("runtime_adapter")
        if not isinstance(runtime_adapter, dict):
            runtime_adapter = payload.get("adapter", {})
        if not isinstance(runtime_adapter, dict):
            runtime_adapter = {}
        adapter_mode = str(runtime_adapter.get("mode", "local") or "local")
        _used_fallback = bool(runtime_adapter.get("used_fallback", False))
        if adapter_mode == "aegis":
            aegis_mode += 1
        else:
            local_mode += 1

    return {
        "exists": True,
        "projects": project_count,
        "total_runs": total_runs,
        "missing_runs": missing_runs,
        "skipped_missing": skipped_missing,
        "passed": passed,
        "failed": failed,
        "aegis_mode": aegis_mode,
        "local_mode": local_mode,
    }


def get_workspace_next_actions(cwd: Path) -> dict:
    data = load_workspace(cwd)
    if data is None:
        return {"exists": False}

    projects = data.get("projects", [])
    suggestions: list[dict[str, object]] = []
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        name = str(item.get("name", Path(path).name if path else ""))
        project_path = Path(path) if path else None
        if project_path is None or not project_path.exists():
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "LOW",
                    "reason": "project missing or moved",
                    "signal": None,
                    "action": "Project missing or moved",
                }
            )
            continue

        latest_path = project_path / ".aegis" / "runs" / "latest.json"
        if not latest_path.exists():
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "MEDIUM",
                    "reason": "not initialized (missing latest run)",
                    "signal": None,
                    "action": "Run: aegis-code probe --run",
                }
            )
            continue

        try:
            payload = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        verification = payload.get("verification", {})
        verification_available = bool(verification.get("available", False)) if isinstance(verification, dict) else False
        final_failures = payload.get("final_failures", {})
        failure_count = 0
        if isinstance(final_failures, dict):
            try:
                failure_count = int(final_failures.get("failure_count", 0) or 0)
            except Exception:
                failure_count = 0
        provider_skipped = bool(payload.get("provider_skipped", False))
        sll_risk = str(payload.get("sll_risk", "") or "").lower()

        if not verification_available:
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "HIGH",
                    "reason": "no verification available",
                    "signal": None,
                    "action": "Run: aegis-code probe --run",
                }
            )
            continue
        if failure_count > 0:
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "HIGH",
                    "reason": f"tests failing ({failure_count} failures)",
                    "signal": f"failures: {failure_count}",
                    "action": "Run: aegis-code fix --max-cycles 1",
                }
            )
            continue
        if provider_skipped:
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "MEDIUM",
                    "reason": "provider step skipped",
                    "signal": None,
                    "action": "Review skip reason and resolve before retry",
                }
            )
            continue
        if sll_risk == "high":
            suggestions.append(
                {
                    "index": index,
                    "name": name,
                    "priority": "MEDIUM",
                    "reason": "SLL risk: high",
                    "signal": None,
                    "action": "Investigate instability before large changes",
                }
            )
            continue
        suggestions.append(
            {
                "index": index,
                "name": name,
                "priority": "LOW",
                "reason": "stable, tests passing",
                "signal": None,
                "action": "No action needed",
            }
        )

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_suggestions = sorted(
        suggestions,
        key=lambda item: (
            order.get(str(item.get("priority", "LOW")), 2),
            int(item.get("index", 0) or 0),
        ),
    )
    return {"exists": True, "projects": sorted_suggestions}


def _is_run_passed(payload: dict) -> bool:
    final_failures = payload.get("final_failures")
    if isinstance(final_failures, dict) and "failure_count" in final_failures:
        try:
            return int(final_failures.get("failure_count", 0) or 0) == 0
        except Exception:
            return False

    failures = payload.get("failures")
    if isinstance(failures, dict) and "failure_count" in failures:
        try:
            return int(failures.get("failure_count", 0) or 0) == 0
        except Exception:
            return False

    test_attempts = payload.get("test_attempts")
    if isinstance(test_attempts, list) and test_attempts:
        latest_attempt = test_attempts[-1]
        if isinstance(latest_attempt, dict):
            exit_code = latest_attempt.get("exit_code")
            status = str(latest_attempt.get("status", "") or "").lower()
            if isinstance(exit_code, int):
                return exit_code == 0
            if status in {"ok", "passed", "success"}:
                return True
            if status:
                return False

    commands_run = payload.get("commands_run")
    if isinstance(commands_run, list):
        test_like = [
            item for item in commands_run
            if isinstance(item, dict) and "test" in str(item.get("name", "")).lower()
        ]
        if test_like:
            latest_test = test_like[-1]
            exit_code = latest_test.get("exit_code")
            status = str(latest_test.get("status", "") or "").lower()
            if isinstance(exit_code, int):
                return exit_code == 0
            if status in {"ok", "passed", "success"}:
                return True
            if status:
                return False

    status = str(payload.get("status", "") or "").lower()
    if status in {"completed_tests_passed", "completed_tests_passed_after_retry"}:
        return True
    if "completed_tests_failed" in status:
        return False
    return False
