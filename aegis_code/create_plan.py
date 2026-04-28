from __future__ import annotations

from pathlib import Path
from typing import Any


def _normalize_idea(idea: str) -> str:
    return " ".join(str(idea or "").strip().split())


def build_create_plan(idea: str, cwd: Path | None = None) -> dict[str, Any]:
    _ = cwd
    normalized = _normalize_idea(idea)
    lowered = normalized.lower()

    if any(token in lowered for token in ("api", "rest", "backend", "fastapi")):
        stack_name = "python-fastapi"
        stack_reason = "API/backend keywords detected."
        structure = [
            {"path": "app/main.py", "purpose": "FastAPI application entrypoint"},
            {"path": "app/routes.py", "purpose": "Route definitions"},
            {"path": "app/models.py", "purpose": "Data models"},
            {"path": "tests/test_app.py", "purpose": "Application tests"},
        ]
        dependencies = ["fastapi", "uvicorn", "pytest"]
        test_command = "python -m pytest -q"
    elif any(token in lowered for token in ("cli", "command", "terminal")):
        stack_name = "python-cli"
        stack_reason = "CLI/terminal keywords detected."
        structure = [
            {"path": "src/main.py", "purpose": "CLI entrypoint"},
            {"path": "tests/test_cli.py", "purpose": "CLI behavior tests"},
            {"path": "README.md", "purpose": "Usage documentation"},
        ]
        dependencies = ["pytest"]
        test_command = "python -m pytest -q"
    elif any(token in lowered for token in ("react", "frontend", "ui", "dashboard")):
        stack_name = "node-react"
        stack_reason = "Frontend/react keywords detected."
        structure = [
            {"path": "src/App.jsx", "purpose": "Main React view"},
            {"path": "src/main.jsx", "purpose": "Application bootstrap"},
            {"path": "tests/App.test.jsx", "purpose": "UI tests"},
            {"path": "package.json", "purpose": "Node scripts and dependencies"},
        ]
        dependencies = ["react", "vite", "vitest"]
        test_command = "npm test"
    else:
        stack_name = "python-basic"
        stack_reason = "Defaulting to a simple Python baseline."
        structure = [
            {"path": "src/main.py", "purpose": "Application entrypoint"},
            {"path": "tests/test_main.py", "purpose": "Baseline tests"},
            {"path": "README.md", "purpose": "Project documentation"},
        ]
        dependencies = ["pytest"]
        test_command = "python -m pytest -q"

    return {
        "idea": normalized,
        "mode": "plan_only",
        "stack": {"name": stack_name, "reason": stack_reason},
        "structure": structure,
        "dependencies": dependencies,
        "test_command": test_command,
        "notes": [
            "Planning only: no project files were created.",
            "Review the plan before scaffolding.",
        ],
        "next_steps": [
            "Use this plan as a starting point.",
            "Future scaffold/write mode should require explicit confirmation.",
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
