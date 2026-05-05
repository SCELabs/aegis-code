from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass(slots=True)
class SafetyIssue:
    type: str
    severity: str
    file: str
    line: str
    message: str
    suggestion: str | None


@dataclass(slots=True)
class SafetyReport:
    issues: list[SafetyIssue]
    highest_severity: str


def default_safety_constraints() -> list[str]:
    return [
        "Do not write outside the project root unless explicitly requested.",
        "Avoid Path.home(), absolute system paths, shell execution, eval/exec, and network calls unless required by the task.",
        "Prefer project-local paths or environment-configurable paths for generated app state.",
        "Keep generated changes testable and avoid hidden global machine state.",
        "Do not read, print, or persist secrets unless explicitly requested.",
    ]


def detect_explicit_risky_intent(task: str) -> dict:
    lowered = str(task or "").lower()
    return {
        "allows_outside_project_write": any(
            token in lowered
            for token in ("home directory", "path.home", "absolute path", "system path", "write to home")
        ),
        "allows_subprocess": any(
            token in lowered for token in ("run shell", "subprocess", "execute command")
        ),
        "allows_network": any(
            token in lowered for token in ("fetch from", "call api", "http://", "https://")
        ),
        "allows_dynamic_execution": any(
            token in lowered for token in ("eval", "exec")
        ),
    }


def render_safety_constraints_for_prompt(task: str = "") -> str:
    intent = detect_explicit_risky_intent(task)
    lines = ["Safety constraints:"]
    lines.append("- Do not read, print, or persist secrets unless explicitly requested.")
    lines.append("- Keep generated changes testable and avoid hidden global machine state.")
    if intent.get("allows_outside_project_write", False):
        lines.append("- The user has explicitly requested behavior that may write outside the project directory.")
        lines.append("- You may implement this, but keep it clear, minimal, and controlled.")
        lines.append("- Prefer project-local or environment-configurable paths unless home/system path behavior is required by the task.")
    else:
        lines.append("- Do not write outside the project root unless explicitly requested.")
        lines.append("- Avoid Path.home() and absolute system paths unless required by the task.")
    if intent.get("allows_subprocess", False):
        lines.append("- Subprocess/shell behavior is explicitly requested; keep it explicit, minimal, and scoped.")
    else:
        lines.append("- Avoid shell execution and subprocess invocation unless required by the task.")
    if intent.get("allows_network", False):
        lines.append("- Network access is explicitly requested; keep calls explicit and test-isolated.")
    else:
        lines.append("- Avoid network calls unless explicitly requested.")
    if intent.get("allows_dynamic_execution", False):
        lines.append("- Dynamic code execution is explicitly requested; keep it minimal and clearly justified.")
    else:
        lines.append("- Avoid eval/exec unless explicitly required.")
    lines.append("- Avoid introducing unrelated risky behavior.")
    return "\n".join(lines) + "\n"


def _issue(type_value: str, file_path: str, line_text: str, message: str, suggestion: str | None) -> SafetyIssue:
    return SafetyIssue(
        type=type_value,
        severity="warn",
        file=file_path,
        line=line_text,
        message=message,
        suggestion=suggestion,
    )


def scan_diff(diff_text: str) -> SafetyReport:
    current_file = ""
    issues: list[SafetyIssue] = []
    for raw in str(diff_text or "").splitlines():
        line = str(raw)
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4 and parts[3].startswith("b/"):
                current_file = parts[3][2:]
            continue
        if line.startswith("+++ "):
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        if "Path.home()" in added or re.search(r"(^|[^A-Za-z])(/home/|[A-Za-z]:\\\\)", added):
            issues.append(
                _issue(
                    "writes_outside_project",
                    current_file,
                    added,
                    "Uses Path.home() or absolute path, which may write outside the project directory.",
                    "Use a project-local path or an environment-configurable path.",
                )
            )
        if any(token in added for token in (".unlink(", "shutil.rmtree", "os.remove", "os.unlink")):
            issues.append(
                _issue(
                    "destructive_filesystem_operation",
                    current_file,
                    added,
                    "Introduces destructive filesystem operations.",
                    "Avoid destructive file deletes unless explicitly required and safeguarded.",
                )
            )
        if any(token in added for token in ("subprocess", "os.system", "Popen(")):
            issues.append(
                _issue(
                    "process_execution",
                    current_file,
                    added,
                    "Introduces shell or subprocess execution.",
                    "Avoid shell execution unless required; keep commands explicit and test-covered.",
                )
            )
        if any(token in added for token in ("eval(", "exec(")):
            issues.append(
                _issue(
                    "dynamic_code_execution",
                    current_file,
                    added,
                    "Introduces dynamic code execution.",
                    "Avoid eval/exec unless explicitly required.",
                )
            )
        if any(token in added for token in ("requests.", "urllib.", "http://", "https://")):
            issues.append(
                _issue(
                    "network_access",
                    current_file,
                    added,
                    "Introduces network access.",
                    "Avoid network calls unless explicitly requested and test-isolated.",
                )
            )
        if any(token in added for token in ("chmod", "chown")):
            issues.append(
                _issue(
                    "permission_change",
                    current_file,
                    added,
                    "Introduces permission or ownership changes.",
                    "Avoid permission changes unless explicitly required.",
                )
            )
        if any(token in added for token in ("os.environ", "API_KEY", "SECRET", "TOKEN")):
            issues.append(
                _issue(
                    "secret_or_env_access",
                    current_file,
                    added,
                    "Introduces environment or secret access.",
                    "Avoid reading or persisting secrets unless explicitly requested.",
                )
            )
    highest = "warn" if issues else "pass"
    return SafetyReport(issues=issues, highest_severity=highest)


def safety_report_to_dict(report: SafetyReport) -> dict:
    return {
        "highest_severity": report.highest_severity,
        "issues": [asdict(item) for item in report.issues],
    }
