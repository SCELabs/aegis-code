from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.aegis_client import AegisBackendClient

if TYPE_CHECKING:
    from aegis_code.runtime import TaskOptions


def execute_task(
    task_options: "TaskOptions",
    *,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    try:
        from aegis import AegisClient  # type: ignore

        _ = AegisClient
    except Exception:
        from aegis_code.runtime import _run_task_local

        return _run_task_local(options=task_options, cwd=cwd, client=client)

    from aegis_code.runtime import _run_task_local

    return _run_task_local(options=task_options, cwd=cwd, client=client)
