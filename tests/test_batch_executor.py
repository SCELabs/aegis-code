from __future__ import annotations

from pathlib import Path

from aegis_code.batch_executor import execute_batch
from aegis_code.batch_schema import BatchDefinition, BatchStep
from aegis_code.operations.runner import OperationResult


def _create_file_diff(path: str, content_line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content_line}\n"
    )


def _replace_file_diff(path: str, old_line: str, new_line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        f"-{old_line}\n"
        f"+{new_line}\n"
    )


def test_batch_executor_single_step_succeeds(monkeypatch, tmp_path: Path) -> None:
    batch = BatchDefinition(
        version=1,
        operations=[
            BatchStep(
                operation="create-file",
                target_file="src/utils.js",
                task="create helper",
            )
        ],
    )

    def _fake_run_operation_stage(**kwargs):
        contract = kwargs["contract"]
        assert contract.operation == "create-file"
        return OperationResult(
            attempted=True,
            status="generated",
            diff_text=_create_file_diff("src/utils.js", "export const x = 1;"),
            operation=contract.operation,
            source=contract.source,
        )

    monkeypatch.setattr("aegis_code.batch_executor.run_operation_stage", _fake_run_operation_stage)
    result = execute_batch(batch=batch, cwd=tmp_path, runtime_context={})
    assert result.success is True
    assert result.total_steps == 1
    assert result.completed_steps == 1
    assert result.failed_step_index is None
    assert len(result.step_results) == 1
    assert result.step_results[0]["operation"] == "create-file"
    assert result.step_results[0]["status"] == "generated"
    assert result.step_results[0]["patch_generated"] is True
    assert result.step_results[0]["error"] is None
    assert "diff --git a/src/utils.js b/src/utils.js" in result.diff_text


def test_batch_executor_multi_step_succeeds(monkeypatch, tmp_path: Path) -> None:
    batch = BatchDefinition(
        version=1,
        operations=[
            BatchStep(operation="create-file", target_file="src/utils.js", task="create helper"),
            BatchStep(operation="replace-file", target_file="src/utils.js", task="replace helper"),
        ],
    )

    def _fake_run_operation_stage(**kwargs):
        contract = kwargs["contract"]
        if contract.operation == "create-file":
            return OperationResult(
                attempted=True,
                status="generated",
                diff_text=_create_file_diff("src/utils.js", "export const x = 1;"),
                operation=contract.operation,
                source=contract.source,
            )
        return OperationResult(
            attempted=True,
            status="generated",
            diff_text=_replace_file_diff("src/utils.js", "export const x = 1;", "export const x = 2;"),
            operation=contract.operation,
            source=contract.source,
        )

    monkeypatch.setattr("aegis_code.batch_executor.run_operation_stage", _fake_run_operation_stage)
    result = execute_batch(batch=batch, cwd=tmp_path, runtime_context={})
    assert result.success is True
    assert result.total_steps == 2
    assert result.completed_steps == 2
    assert len(result.step_results) == 2
    assert [item["status"] for item in result.step_results] == ["generated", "generated"]
    assert "export const x = 2;" in result.diff_text
    assert "export const x = 1;" not in result.diff_text


def test_batch_executor_step_failure_aborts(monkeypatch, tmp_path: Path) -> None:
    batch = BatchDefinition(
        version=1,
        operations=[
            BatchStep(operation="create-file", target_file="src/utils.js", task="create helper"),
            BatchStep(operation="replace-symbol", target_file="src/main.js", symbol="run", task="replace symbol"),
        ],
    )

    def _fake_run_operation_stage(**kwargs):
        contract = kwargs["contract"]
        if contract.operation == "create-file":
            return OperationResult(
                attempted=True,
                status="generated",
                diff_text=_create_file_diff("src/utils.js", "export const x = 1;"),
                operation=contract.operation,
                source=contract.source,
            )
        return OperationResult(
            attempted=True,
            status="blocked",
            error="operation_validation_failed",
            operation=contract.operation,
            source=contract.source,
        )

    monkeypatch.setattr("aegis_code.batch_executor.run_operation_stage", _fake_run_operation_stage)
    result = execute_batch(batch=batch, cwd=tmp_path, runtime_context={})
    assert result.success is False
    assert result.total_steps == 2
    assert result.completed_steps == 1
    assert result.failed_step_index == 2
    assert result.error == "operation_validation_failed"
    assert len(result.step_results) == 2
    assert result.step_results[1]["operation"] == "replace-symbol"
    assert result.step_results[1]["target_file"] == "src/main.js"
    assert result.step_results[1]["status"] == "blocked"
    assert result.step_results[1]["patch_generated"] is False
    assert result.step_results[1]["error"] == "operation_validation_failed"


def test_batch_executor_combined_diff_includes_all_successful_changes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.js").write_text("export const main = 1;\n", encoding="utf-8")
    batch = BatchDefinition(
        version=1,
        operations=[
            BatchStep(operation="create-file", target_file="src/utils.js", task="create helper"),
            BatchStep(operation="replace-file", target_file="src/main.js", task="update main"),
        ],
    )

    def _fake_run_operation_stage(**kwargs):
        contract = kwargs["contract"]
        if contract.target_file == "src/utils.js":
            return OperationResult(
                attempted=True,
                status="generated",
                diff_text=_create_file_diff("src/utils.js", "export const helper = 1;"),
                operation=contract.operation,
                source=contract.source,
            )
        return OperationResult(
            attempted=True,
            status="generated",
            diff_text=_replace_file_diff("src/main.js", "export const main = 1;", "export const main = 2;"),
            operation=contract.operation,
            source=contract.source,
        )

    monkeypatch.setattr("aegis_code.batch_executor.run_operation_stage", _fake_run_operation_stage)
    result = execute_batch(batch=batch, cwd=tmp_path, runtime_context={})
    assert result.success is True
    assert "diff --git a/src/utils.js b/src/utils.js" in result.diff_text
    assert "diff --git a/src/main.js b/src/main.js" in result.diff_text


def test_batch_executor_temp_workspace_cleaned_up(monkeypatch, tmp_path: Path) -> None:
    batch = BatchDefinition(
        version=1,
        operations=[
            BatchStep(operation="create-file", target_file="src/utils.js", task="create helper"),
        ],
    )

    class _RecordingTempDir:
        last_path: Path | None = None

        def __init__(self, prefix: str = "") -> None:
            self.path = Path(tmp_path.parent / f"{prefix}workspace_temp")

        def __enter__(self) -> str:
            if self.path.exists():
                for item in sorted(self.path.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                self.path.rmdir()
            self.path.mkdir(parents=True, exist_ok=True)
            _RecordingTempDir.last_path = self.path
            return str(self.path)

        def __exit__(self, exc_type, exc, tb) -> None:
            if self.path.exists():
                for item in sorted(self.path.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                self.path.rmdir()

    def _fake_run_operation_stage(**kwargs):
        contract = kwargs["contract"]
        return OperationResult(
            attempted=True,
            status="generated",
            diff_text=_create_file_diff("src/utils.js", "export const x = 1;"),
            operation=contract.operation,
            source=contract.source,
        )

    monkeypatch.setattr("aegis_code.batch_executor.run_operation_stage", _fake_run_operation_stage)
    monkeypatch.setattr("aegis_code.batch_executor.tempfile.TemporaryDirectory", _RecordingTempDir)
    result = execute_batch(batch=batch, cwd=tmp_path, runtime_context={})
    assert result.success is True
    assert _RecordingTempDir.last_path is not None
    assert _RecordingTempDir.last_path.exists() is False
