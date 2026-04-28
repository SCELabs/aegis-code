from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_code.context.capabilities import detect_capabilities
from aegis_code.patches.backups import list_backups


def _latest_payload(cwd: Path) -> dict[str, Any] | None:
    latest = cwd / ".aegis" / "runs" / "latest.json"
    if not latest.exists():
        return None
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _run_artifact_count(cwd: Path) -> int:
    runs_dir = cwd / ".aegis" / "runs"
    if not runs_dir.exists():
        return 0
    return sum(1 for item in runs_dir.rglob("*") if item.is_file())


def build_maintenance_report(cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    caps = detect_capabilities(root)
    payload = _latest_payload(root)
    backups = list_backups(cwd=root).get("backups", [])
    backup_count = len(backups)
    run_artifact_count = _run_artifact_count(root)

    verification_available = bool(caps.get("verification_available", False))
    test_command = caps.get("test_command")
    detected_stack = caps.get("detected_stack")

    failure_count: int | None = None
    if payload:
        final_failures = payload.get("final_failures", payload.get("failures", {}))
        if isinstance(final_failures, dict):
            raw_failure_count = final_failures.get("failure_count", 0)
            try:
                failure_count = int(raw_failure_count)
            except Exception:
                failure_count = 0

    if not verification_available:
        verification_status = "unavailable"
    elif failure_count is None:
        verification_status = "unknown"
    elif failure_count == 0:
        verification_status = "passing"
    else:
        verification_status = "failing"

    sll = payload.get("sll_analysis", {}) if payload else {}
    sll_available = bool(isinstance(sll, dict) and sll.get("available", False))
    if sll_available:
        risks = {
            "collapse_risk": float(sll.get("collapse_risk", 0.0)),
            "fragmentation_risk": float(sll.get("fragmentation_risk", 0.0)),
            "drift_risk": float(sll.get("drift_risk", 0.0)),
            "stable_random_risk": float(sll.get("stable_random_risk", 0.0)),
        }
        regime = str(sll.get("regime", "unknown"))
        structure_summary = "Structural analysis present from latest run."
    else:
        risks = {}
        regime = None
        structure_summary = "No structural analysis available from latest run."

    issues: list[str] = []
    suggestions: list[str] = []

    if not test_command:
        issues.append("no_test_command")
        suggestions.append("Add a test command to .aegis/aegis-code.yml to enable verified fixes.")
        suggestions.append("Run aegis-code doctor to inspect repo capabilities.")
    if payload is None:
        issues.append("latest_run_missing")
        if verification_available:
            suggestions.append('Run aegis-code "triage current test failures" to create a baseline report.')
    if verification_status == "failing":
        issues.append("tests_failing")
        suggestions.append("Run aegis-code fix to generate a supervised repair proposal.")
    if run_artifact_count > 20:
        issues.append("many_run_artifacts")
        suggestions.append("Consider cleaning old .aegis/runs artifacts.")
    if backup_count > 10:
        issues.append("many_backups")
        suggestions.append("Review backups with aegis-code backups.")
    if not suggestions:
        suggestions.append("No immediate maintenance actions detected.")

    return {
        "verification": {
            "available": verification_available,
            "test_command": test_command,
            "detected_stack": detected_stack,
            "status": verification_status,
            "failure_count": failure_count,
        },
        "structure": {
            "sll_available": sll_available,
            "regime": regime,
            "risks": risks,
            "summary": structure_summary,
        },
        "hygiene": {
            "issues": issues,
            "run_artifact_count": run_artifact_count,
            "backup_count": backup_count,
        },
        "suggestions": suggestions,
    }


def format_maintenance_report(report: dict[str, Any]) -> str:
    verification = report.get("verification", {})
    structure = report.get("structure", {})
    hygiene = report.get("hygiene", {})
    suggestions = report.get("suggestions", [])
    issues = hygiene.get("issues", [])
    risks = structure.get("risks", {})
    regime = structure.get("regime")
    sll_available = bool(structure.get("sll_available", False))
    failure_count = verification.get("failure_count")
    failure_count_str = "n/a" if failure_count is None else str(failure_count)

    lines = [
        "Repo health:",
        "",
        "Verification:",
        f"- Status: {verification.get('status', 'unknown')}",
        f"- Stack: {verification.get('detected_stack') or 'unknown'}",
        f"- Command: {verification.get('test_command') or 'none'}",
        f"- Failure count: {failure_count_str}",
        "",
        "Structure:",
        f"- SLL: {'available' if sll_available else 'unavailable'}",
        f"- Regime: {regime or 'n/a'}",
        f"- Summary: {structure.get('summary', '')}",
    ]
    if risks:
        lines.append(f"- Risks: {json.dumps(risks, sort_keys=True)}")
    lines.extend(
        [
            "",
            "Hygiene:",
            f"- Run artifacts: {hygiene.get('run_artifact_count', 0)}",
            f"- Backups: {hygiene.get('backup_count', 0)}",
            f"- Issues: {', '.join(str(item) for item in issues) if issues else 'none'}",
            "",
            "Suggestions:",
        ]
    )
    for suggestion in suggestions:
        lines.append(f"- {suggestion}")
    return "\n".join(lines)
