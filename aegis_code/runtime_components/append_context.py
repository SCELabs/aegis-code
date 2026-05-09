from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _line_tail_capped(text: str, max_lines: int, max_chars: int) -> str:
    lines = str(text or "").splitlines()
    tail = lines[-max_lines:] if max_lines > 0 else lines
    rendered = "\n".join(tail)
    if len(rendered) <= max_chars:
        return rendered
    trimmed = rendered[-max_chars:]
    if "\n" in trimmed:
        trimmed = trimmed[trimmed.find("\n") + 1 :]
    return trimmed


def _build_append_target_context(*, cwd: Path, target_path: str, original_text: str) -> dict[str, Any]:
    imports: list[str] = []
    names: list[str] = []
    tests: list[str] = []
    js_style = "unknown"
    js_test_framework = "unknown"
    package_type = "commonjs"
    target_is_js = str(target_path).replace("\\", "/").lower().endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"))
    if target_is_js:
        package_json = cwd / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
                if isinstance(pkg, dict):
                    package_type = str(pkg.get("type", "commonjs") or "commonjs").strip().lower()
            except Exception:
                package_type = "commonjs"
    for raw_line in str(original_text or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
        fn_match = re.match(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
        if fn_match:
            name = fn_match.group(1)
            names.append(name)
            if name.startswith("test_"):
                tests.append(name)
        class_test_match = re.match(r"^\s*def\s+(test_[A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
        if class_test_match:
            tests.append(class_test_match.group(1))
        if target_is_js:
            if stripped.startswith("import "):
                js_style = "esm"
            if "require(" in stripped and js_style == "unknown":
                js_style = "commonjs"
            if stripped.startswith("export ") or "module.exports" in stripped:
                names.append(stripped)
            js_fn_match = re.match(r"^\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
            if js_fn_match:
                names.append(js_fn_match.group(1))
            if "node:test" in stripped or " from \"node:test\"" in stripped or " from 'node:test'" in stripped:
                js_test_framework = "node:test"
            if "describe(" in stripped or "expect(" in stripped:
                if js_test_framework == "unknown":
                    js_test_framework = "jest_like"
    if target_is_js and js_style == "unknown":
        js_style = "esm" if package_type == "module" or str(target_path).endswith(".mjs") else "commonjs"
    return {
        "path": target_path,
        "imports": sorted(set(imports), key=str.lower)[:40],
        "existing_names": sorted(set(names), key=str.lower)[:80],
        "existing_tests": sorted(set(tests), key=str.lower)[:80],
        "js_module_system": js_style if target_is_js else "n/a",
        "js_test_framework": js_test_framework if target_is_js else "n/a",
        "package_json_type": package_type if target_is_js else "n/a",
        "tail": _line_tail_capped(original_text, 80, 4000),
    }

