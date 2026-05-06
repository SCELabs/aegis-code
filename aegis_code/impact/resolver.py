from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass
class FailureSignal:
    type: str
    files: list[str]
    message: str
    raw: str


@dataclass
class ImpactSuggestion:
    files: list[str]
    reason: str
    command: str | None
    confidence: str


@dataclass
class ImpactReport:
    signals: list[FailureSignal]
    suggestions: list[ImpactSuggestion]
    summary: str


_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+)")
_IGNORE_PARTS = {".aegis", ".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache", ".cache", "cache"}

_SIGNAL_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("import_error", ("ImportError", "ModuleNotFoundError", "Cannot find module", "unresolved import", "cannot find package")),
    ("assertion_failure", ("AssertionError", "expected", "received", "Expected:", "Received:", "assert")),
    ("name_error", ("NameError", "ReferenceError", "undefined", "is not defined")),
    ("build_error", ("failed to compile", "compilation failed", "SyntaxError", "ParseError", "TypeError")),
    ("runtime_error", ("Traceback", "panic:", "RuntimeError", "Exception", "error:")),
    ("test_failure", ("FAIL", "FAILED", "failing", "test failed")),
]


def _norm(path: str) -> str:
    return path.strip().strip("'\"`()[]{}<>").replace("\\", "/")


def _ignored(path: str) -> bool:
    parts = [p for p in _norm(path).split("/") if p]
    return any(part in _IGNORE_PARTS for part in parts)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_paths(raw_output: str, repo_files: list[str] | None) -> list[str]:
    tokens = [_norm(m.group(1)) for m in _PATH_RE.finditer(raw_output or "")]
    tokens = [p for p in tokens if "/" in p or "." in p]
    tokens = [p for p in tokens if not _ignored(p)]
    if repo_files:
        repo_set = {_norm(p) for p in repo_files}
        matched = [p for p in tokens if p in repo_set]
        if matched:
            return _dedupe(matched)
    return _dedupe(tokens)


def _signal_type(raw_output: str, exit_code: int | None) -> str:
    if (exit_code is not None and int(exit_code) != 0) and not str(raw_output or "").strip():
        return "runtime_error"
    lowered = str(raw_output or "").lower()
    for signal_type, keywords in _SIGNAL_PATTERNS:
        for keyword in keywords:
            if keyword.lower() in lowered:
                return signal_type
    return "runtime_error" if lowered else "test_failure"


def _concise_message(raw_output: str, signal_type: str) -> str:
    for line in (raw_output or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if len(text) > 180:
            text = text[:177] + "..."
        return f"{signal_type}: {text}"
    return signal_type


def _is_test_file(path: str) -> bool:
    value = _norm(path).lower()
    name = value.split("/")[-1]
    return value.startswith("tests/") or "/test/" in value or name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.js") or name.endswith(".spec.js")


def extract_failure_signals(
    *,
    raw_output: str,
    exit_code: int | None = None,
    changed_files: list[str] | None = None,
    repo_files: list[str] | None = None,
) -> list[FailureSignal]:
    if (exit_code is None or int(exit_code) == 0) and not str(raw_output or "").strip():
        return []
    files = _extract_paths(raw_output, repo_files)
    if not files and changed_files:
        files = _dedupe([_norm(p) for p in changed_files if not _ignored(str(p))])
    signal_type = _signal_type(raw_output, exit_code)
    return [
        FailureSignal(
            type=signal_type,
            files=files,
            message=_concise_message(raw_output, signal_type),
            raw=str(raw_output or ""),
        )
    ]


def _build_command(files: list[str], reason: str) -> str | None:
    if not files:
        return None
    reason_text = reason.strip() or "verification_failure"
    if len(files) == 1:
        return f'aegis-code patch --file {files[0]} "address verification failure related to {reason_text}"'
    flags = " ".join(f"--file {item}" for item in files[:2])
    return f'aegis-code patch {flags} --max-files 2 "address verification failure related to {reason_text}"'


def resolve_impact(
    *,
    signals: list[FailureSignal],
    changed_files: list[str],
    repo_files: list[str],
    task: str,
) -> ImpactReport:
    _ = repo_files, task
    suggestions: list[ImpactSuggestion] = []
    for signal in signals:
        test_files = [f for f in signal.files if _is_test_file(f)]
        source_files = [f for f in signal.files if f not in test_files]
        chosen: list[str] = []
        reason = signal.type
        confidence = "medium"
        if test_files:
            chosen = test_files[:2]
            if signal.type == "assertion_failure":
                reason = "assertion_failure_in_test"
        elif source_files:
            chosen = source_files[:2]
            if signal.type in {"import_error", "name_error", "build_error"}:
                reason = f"{signal.type}_in_source"
                confidence = "high"
        if chosen:
            suggestions.append(
                ImpactSuggestion(
                    files=chosen,
                    reason=reason,
                    command=_build_command(chosen, reason),
                    confidence=confidence,
                )
            )
    if not suggestions and changed_files:
        fallback_files = _dedupe([_norm(p) for p in changed_files if not _ignored(str(p))])[:2]
        suggestions.append(
            ImpactSuggestion(
                files=fallback_files,
                reason="review_recent_changes",
                command=_build_command(fallback_files, "review_recent_changes"),
                confidence="low",
            )
        )
    summary = "No impact analysis needed." if not signals else "Verification failed. Suggested bounded next patch targets identified."
    return ImpactReport(signals=signals, suggestions=suggestions, summary=summary)


def impact_report_to_dict(report: ImpactReport) -> dict[str, object]:
    return {
        "summary": report.summary,
        "signals": [asdict(item) for item in report.signals],
        "suggestions": [asdict(item) for item in report.suggestions],
    }
