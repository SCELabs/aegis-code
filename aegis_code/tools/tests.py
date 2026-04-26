from __future__ import annotations

from pathlib import Path

from aegis_code.models import CommandResult
from aegis_code.tools.shell import run_shell_command


def run_configured_tests(command: str, cwd: Path | None = None) -> CommandResult:
    return run_shell_command(name="test", command=command, cwd=cwd)
