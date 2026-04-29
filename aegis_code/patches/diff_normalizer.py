from __future__ import annotations

from pathlib import PurePosixPath


def _normalize_path(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return str(PurePosixPath(value))


def normalize_unified_diff(diff_text: str) -> str:
    text = str(diff_text or "")
    if not text.strip():
        return text

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            out.append(line)
            i += 1
            continue

        if i > 0 and lines[i - 1].startswith("diff --git ") and line.startswith("--- ") and (i + 1) < len(lines) and lines[i + 1].startswith("+++ "):
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            continue

        if line.startswith("--- ") and (i + 1) < len(lines) and lines[i + 1].startswith("+++ "):
            old_raw = line[4:].strip()
            new_raw = lines[i + 1][4:].strip()
            if old_raw != "/dev/null":
                base = _normalize_path(old_raw)
            elif new_raw != "/dev/null":
                base = _normalize_path(new_raw)
            else:
                base = ""
            if base:
                out.append(f"diff --git a/{base} b/{base}")
            out.append(f"--- {'/dev/null' if old_raw == '/dev/null' else f'a/{_normalize_path(old_raw)}'}")
            out.append(f"+++ {'/dev/null' if new_raw == '/dev/null' else f'b/{_normalize_path(new_raw)}'}")
            i += 2
            continue

        out.append(line)
        i += 1

    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"
    return result
