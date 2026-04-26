from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from aegis_code.models import CommandResult

UNSAFE_TOKENS = {"&&", "||", ";", "|", ">", "<"}


def is_safe_command(command: str) -> bool:
    return not any(token in command for token in UNSAFE_TOKENS)


def run_shell_command(
    *, name: str, command: str, cwd: Path | None = None, timeout_seconds: int = 120
) -> CommandResult:
    if not command.strip():
        return CommandResult(name=name, command=command, status="skipped")
    if not is_safe_command(command):
        return CommandResult(
            name=name,
            command=command,
            status="skipped_unsafe",
            output_preview="Command contains unsupported shell control tokens.",
        )

    try:
        parts = shlex.split(command, posix=False)
        completed = subprocess.run(
            parts,
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        return CommandResult(
            name=name,
            command=command,
            status="ok" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            output_preview=output[:1200],
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            name=name,
            command=command,
            status="timeout",
            output_preview=f"Command timed out after {timeout_seconds}s.",
        )
    except Exception as exc:
        return CommandResult(
            name=name,
            command=command,
            status="error",
            output_preview=str(exc),
        )
