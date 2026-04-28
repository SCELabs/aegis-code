from __future__ import annotations

from pathlib import Path
from typing import Any


MAX_DOC_BYTES = 100 * 1024
MAX_DOC_LINES = 250


def _context_paths(cwd: Path) -> dict[str, Path]:
    context_dir = cwd / ".aegis" / "context"
    return {
        "dir": context_dir,
        "project_summary": context_dir / "project_summary.md",
        "architecture": context_dir / "architecture.md",
        "constraints": context_dir / "constraints.md",
    }


def _read_limited(path: Path) -> str:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle):
            if idx >= MAX_DOC_LINES:
                break
            lines.append(line.rstrip("\n"))
    return "\n".join(lines).strip()


def _safe_rel(path: Path, cwd: Path) -> str:
    return path.relative_to(cwd).as_posix()


def _discover_docs(cwd: Path) -> list[Path]:
    docs_dir = cwd / "docs"
    if not docs_dir.exists() or not docs_dir.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(cwd).parts):
            continue
        if path.stat().st_size > MAX_DOC_BYTES:
            continue
        found.append(path)
    return found


def refresh_context(cwd: Path | None = None) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    paths = _context_paths(root)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    readme = root / "README.md"
    pyproject = root / "pyproject.toml"
    package_json = root / "package.json"
    docs = _discover_docs(root)

    summary_sections: list[str] = [
        "# Project Summary",
        "",
        "Deterministic local context generated from selected repository files.",
        "",
    ]
    summary_sources: list[str] = []

    if readme.exists():
        summary_sources.append(_safe_rel(readme, root))
        summary_sections.extend(
            [
                "## README Excerpt",
                _read_limited(readme),
                "",
            ]
        )
    if pyproject.exists():
        summary_sources.append(_safe_rel(pyproject, root))
        summary_sections.extend(
            [
                "## pyproject.toml Excerpt",
                "```toml",
                _read_limited(pyproject),
                "```",
                "",
            ]
        )
    if package_json.exists():
        summary_sources.append(_safe_rel(package_json, root))
        summary_sections.extend(
            [
                "## package.json Excerpt",
                "```json",
                _read_limited(package_json),
                "```",
                "",
            ]
        )

    architecture_sections: list[str] = [
        "# Architecture Context",
        "",
        "Deterministic local context generated from architecture-oriented docs.",
        "",
    ]
    architecture_sources: list[str] = []

    constraints_sections: list[str] = [
        "# Constraints Context",
        "",
        "Deterministic local context generated from constraints-oriented docs.",
        "",
    ]
    constraints_sources: list[str] = []

    for doc in docs:
        name = doc.name.lower()
        rel = _safe_rel(doc, root)
        if any(token in name for token in ("architecture", "design", "system", "overview")):
            architecture_sources.append(rel)
            architecture_sections.extend([f"## {rel}", _read_limited(doc), ""])
            continue
        if any(token in name for token in ("constraint", "constraints", "requirement", "requirements", "rules", "safety")):
            constraints_sources.append(rel)
            constraints_sections.extend([f"## {rel}", _read_limited(doc), ""])
            continue
        summary_sources.append(rel)
        summary_sections.append(f"- Additional doc: {rel}")

    summary_sections.extend(["", "## Sources"])
    summary_sections.extend([f"- {item}" for item in sorted(set(summary_sources))] or ["- none"])

    architecture_sections.extend(["", "## Sources"])
    architecture_sections.extend([f"- {item}" for item in sorted(set(architecture_sources))] or ["- none"])

    constraints_sections.extend(["", "## Sources"])
    constraints_sections.extend([f"- {item}" for item in sorted(set(constraints_sources))] or ["- none"])

    paths["project_summary"].write_text("\n".join(summary_sections).strip() + "\n", encoding="utf-8")
    paths["architecture"].write_text("\n".join(architecture_sections).strip() + "\n", encoding="utf-8")
    paths["constraints"].write_text("\n".join(constraints_sections).strip() + "\n", encoding="utf-8")

    return {
        "exists": True,
        "context_dir": str(paths["dir"]),
        "files": {
            "project_summary": str(paths["project_summary"]),
            "architecture": str(paths["architecture"]),
            "constraints": str(paths["constraints"]),
        },
        "sources": {
            "project_summary": sorted(set(summary_sources)),
            "architecture": sorted(set(architecture_sources)),
            "constraints": sorted(set(constraints_sources)),
        },
    }


def show_context(cwd: Path | None = None) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    paths = _context_paths(root)
    files = [paths["project_summary"], paths["architecture"], paths["constraints"]]
    if not all(path.exists() for path in files):
        return {"exists": False, "files": {}}
    previews: dict[str, list[str]] = {}
    for path in files:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previews[path.name] = lines[:3]
    return {
        "exists": True,
        "files": {
            "project_summary": str(paths["project_summary"]),
            "architecture": str(paths["architecture"]),
            "constraints": str(paths["constraints"]),
        },
        "previews": previews,
    }


def format_context_refresh(result: dict[str, Any]) -> str:
    lines = [
        "Context refreshed.",
        f"Context dir: {result.get('context_dir', '.aegis/context')}",
        "Files:",
    ]
    files = result.get("files", {})
    lines.append(f"- {files.get('project_summary', '.aegis/context/project_summary.md')}")
    lines.append(f"- {files.get('architecture', '.aegis/context/architecture.md')}")
    lines.append(f"- {files.get('constraints', '.aegis/context/constraints.md')}")
    return "\n".join(lines)


def format_context_show(result: dict[str, Any]) -> str:
    if not result.get("exists", False):
        return "No project context found. Run `aegis-code context refresh`."
    files = result.get("files", {})
    previews = result.get("previews", {})
    lines = [
        "Project context:",
        "Exists: true",
        "Files:",
        f"- {files.get('project_summary', '.aegis/context/project_summary.md')}",
        f"- {files.get('architecture', '.aegis/context/architecture.md')}",
        f"- {files.get('constraints', '.aegis/context/constraints.md')}",
        "Preview:",
    ]
    for name, preview_lines in previews.items():
        lines.append(f"- {name}")
        for item in preview_lines:
            lines.append(f"  {item}")
    return "\n".join(lines)


def load_runtime_context(cwd: Path | None = None, max_chars: int = 6000) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    paths = _context_paths(root)
    ordered = [
        ("project_summary", paths["project_summary"]),
        ("constraints", paths["constraints"]),
        ("architecture", paths["architecture"]),
    ]
    available_files = [(name, path) for name, path in ordered if path.exists()]
    if not available_files:
        return {
            "available": False,
            "files": {},
            "included_paths": [],
            "total_chars": 0,
        }

    remaining = max(0, int(max_chars))
    included: dict[str, str] = {}
    included_paths: list[str] = []
    total = 0
    marker = "\n[truncated for runtime context budget]"

    for name, path in available_files:
        if remaining <= 0:
            break
        content = path.read_text(encoding="utf-8")
        rel = _safe_rel(path, root)
        if len(content) <= remaining:
            included[name] = content
            included_paths.append(rel)
            remaining -= len(content)
            total += len(content)
            continue
        if remaining <= len(marker):
            break
        kept = content[: remaining - len(marker)].rstrip()
        included[name] = f"{kept}{marker}"
        included_paths.append(rel)
        total += len(included[name])
        remaining = 0
        break

    return {
        "available": bool(included),
        "files": included,
        "included_paths": included_paths,
        "total_chars": total,
    }
