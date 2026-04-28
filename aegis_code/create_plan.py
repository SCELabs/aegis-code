from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.scaffolds import resolve_stack_profile, select_stack_profile


def _normalize_idea(idea: str) -> str:
    return " ".join(str(idea or "").strip().split())


def build_create_plan(idea: str, cwd: Path | None = None, stack_id: str | None = None) -> dict[str, Any]:
    _ = cwd
    normalized = _normalize_idea(idea)

    if stack_id:
        profile = resolve_stack_profile(stack_id)
        stack_reason = f"Explicit stack override requested: {profile['id']}."
    else:
        profile, stack_reason = select_stack_profile(normalized)

    return {
        "idea": normalized,
        "mode": "plan_only",
        "stack": {
            "name": profile["id"],
            "display_name": profile["display_name"],
            "version": profile["version"],
            "reason": stack_reason,
        },
        "structure": profile["structure"],
        "dependencies": profile["dependencies"],
        "test_command": profile["test_command"],
        "notes": [
            "Planning only: no project files were created.",
            "Review the plan before scaffolding.",
            *list(profile.get("notes", [])),
        ],
        "next_steps": [
            "Use this plan as a starting point.",
            "Use --target PATH --confirm to write scaffold files.",
        ],
    }


def format_create_plan(plan: dict[str, Any]) -> str:
    lines = [
        "Project plan:",
        "",
        "Idea:",
        f"- {plan.get('idea', '')}",
        "",
        "Stack:",
        f"- Name: {plan.get('stack', {}).get('name', 'unknown')}",
        f"- Version: {plan.get('stack', {}).get('version', 'unknown')}",
        f"- Reason: {plan.get('stack', {}).get('reason', '')}",
        "",
        "Structure:",
    ]
    for item in plan.get("structure", []):
        lines.append(f"- {item.get('path', '')} -- {item.get('purpose', '')}")
    lines.extend(
        [
            "",
            "Dependencies:",
        ]
    )
    for dep in plan.get("dependencies", []):
        lines.append(f"- {dep}")
    lines.extend(
        [
            "",
            "Verification:",
            f"- Test command: {plan.get('test_command', '')}",
            "",
            "Notes:",
        ]
    )
    for note in plan.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "Next steps:",
        ]
    )
    for step in plan.get("next_steps", []):
        lines.append(f"- {step}")
    return "\n".join(lines)
