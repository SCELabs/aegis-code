from __future__ import annotations

import re
from typing import Any


_PROFILES: dict[str, dict[str, Any]] = {
    "python-basic": {
        "id": "python-basic",
        "display_name": "Python Basic",
        "keywords": ["python", "script", "utility", "tool"],
        "structure": [
            {"path": "src/main.py", "purpose": "Application entrypoint"},
            {"path": "tests/test_main.py", "purpose": "Baseline tests"},
            {"path": "README.md", "purpose": "Project documentation"},
        ],
        "dependencies": ["pytest"],
        "test_command": "python -m pytest -q",
        "version": "0.1",
        "notes": ["Default baseline profile for simple Python projects."],
    },
    "python-cli": {
        "id": "python-cli",
        "display_name": "Python CLI",
        "keywords": ["cli", "command", "terminal"],
        "structure": [
            {"path": "src/main.py", "purpose": "CLI entrypoint"},
            {"path": "tests/test_cli.py", "purpose": "CLI behavior tests"},
            {"path": "README.md", "purpose": "Usage documentation"},
        ],
        "dependencies": ["pytest"],
        "test_command": "python -m pytest -q",
        "version": "0.1",
        "notes": ["Lightweight command-line layout."],
    },
    "python-fastapi": {
        "id": "python-fastapi",
        "display_name": "Python FastAPI",
        "keywords": ["api", "rest", "backend", "fastapi"],
        "structure": [
            {"path": "app/main.py", "purpose": "FastAPI application entrypoint"},
            {"path": "app/routes.py", "purpose": "Route definitions"},
            {"path": "app/models.py", "purpose": "Data models"},
            {"path": "tests/test_app.py", "purpose": "Application tests"},
        ],
        "dependencies": ["fastapi", "uvicorn", "pytest"],
        "test_command": "python -m pytest -q",
        "version": "0.1",
        "notes": ["API-first starter profile using FastAPI conventions."],
    },
    "node-react": {
        "id": "node-react",
        "display_name": "Node React",
        "keywords": ["react", "frontend", "ui", "dashboard"],
        "structure": [
            {"path": "src/App.jsx", "purpose": "Main React view"},
            {"path": "src/main.jsx", "purpose": "Application bootstrap"},
            {"path": "tests/App.test.jsx", "purpose": "UI tests"},
            {"path": "package.json", "purpose": "Node scripts and dependencies"},
        ],
        "dependencies": ["react", "vite", "vitest"],
        "test_command": "npm test",
        "version": "0.1",
        "notes": ["Frontend starter profile for React/Vite projects."],
    },
}


def available_stack_ids() -> list[str]:
    return sorted(_PROFILES.keys())


def list_stacks() -> list[dict[str, Any]]:
    return [resolve_stack_profile(stack_id) for stack_id in available_stack_ids()]


def resolve_stack_profile(stack_id: str) -> dict[str, Any]:
    profile = _PROFILES.get(stack_id)
    if not profile:
        available = ", ".join(available_stack_ids())
        raise ValueError(f"Unknown stack '{stack_id}'. Available stacks: {available}")
    return profile


def select_stack_profile(idea: str) -> tuple[dict[str, Any], str]:
    lowered = str(idea or "").lower()
    tokenized = f" {re.sub(r'[^a-z0-9]+', ' ', lowered)} "

    def _has_signal(signal: str) -> bool:
        normalized = signal.strip().lower()
        if " " in normalized:
            return normalized in lowered
        return f" {normalized} " in tokenized
    cli_signals = (
        "cli",
        "command",
        "terminal",
        "shell",
        "script",
        "tool",
        "command-line",
        "argparse",
        "click",
        "typer",
    )
    react_signals = (
        "react",
        "dashboard",
        "frontend",
        "ui",
        "web app",
        "vite",
        "component",
        "browser",
    )
    api_signals = ("api", "rest", "backend", "fastapi", "endpoint")

    if any(_has_signal(signal) for signal in api_signals):
        best = _PROFILES["python-fastapi"]
        best_score = 1
    elif any(_has_signal(signal) for signal in react_signals):
        best = _PROFILES["node-react"]
        best_score = 1
    elif any(_has_signal(signal) for signal in cli_signals):
        best = _PROFILES["python-cli"]
        best_score = 1
    else:
        best = _PROFILES["python-basic"]
        best_score = 0

    if best_score == 0:
        for stack_id in available_stack_ids():
            profile = _PROFILES[stack_id]
            keywords = profile.get("keywords", [])
            score = sum(1 for keyword in keywords if keyword in lowered)
            if score > best_score:
                best = profile
                best_score = score
    if best["id"] == "python-basic":
        return best, "Defaulting to a simple Python baseline."
    return best, f"Keyword scoring selected {best['id']}."
