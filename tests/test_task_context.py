from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.runtime import TaskOptions, build_run_payload, build_task_context
from tests.helpers import command_result_from_output, pytest_output_pass


class _Client:
    def __init__(self) -> None:
        self.decision = AegisDecision(
            model_tier="mid",
            context_mode="focused",
            max_retries=0,
            allow_escalation=False,
            execution={},
        )

    def step_scope(self, **_: object) -> AegisDecision:
        return self.decision


def test_task_context_includes_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    context = build_task_context(tmp_path)
    paths = [item.get("path") for item in context.get("files", [])]
    assert "src/main.py" in paths


def test_task_context_includes_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    context = build_task_context(tmp_path)
    paths = [item.get("path") for item in context.get("files", [])]
    assert "tests/test_app.py" in paths


def test_task_context_excludes_internal_dirs(tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "hidden.py").write_text("x=1\n", encoding="utf-8")
    context = build_task_context(tmp_path)
    paths = [str(item.get("path", "")) for item in context.get("files", [])]
    assert not any(path.startswith(".aegis/") for path in paths)


def test_task_context_non_empty_for_task_mode(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    context = build_task_context(tmp_path)
    assert isinstance(context.get("files"), list)
    assert len(context["files"]) > 0


def test_aegis_context_optional_refinement(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "secrets.local.json").write_text('{"AEGIS_API_KEY":"x"}', encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    class _FakeAuto:
        def context(self, **_: object) -> dict:
            return {"cleaned_messages": [{"role": "assistant", "content": '{"files":[{"path":"main.py","content":"refined"}]}'}]}

    class _FakeAegisClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeAuto:
            return _FakeAuto()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeAegisClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)

    payload = build_run_payload(
        options=TaskOptions(task="implement feature", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    files = payload.get("failure_context", {}).get("files", [])
    assert files and files[0].get("content") == "refined"


def test_aegis_context_fallback(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "secrets.local.json").write_text('{"AEGIS_API_KEY":"x"}', encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    class _FakeAuto:
        def context(self, **_: object) -> dict:
            raise RuntimeError("boom")

    class _FakeAegisClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeAuto:
            return _FakeAuto()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeAegisClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)

    payload = build_run_payload(
        options=TaskOptions(task="implement feature", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    files = payload.get("failure_context", {}).get("files", [])
    assert any(item.get("path") == "main.py" for item in files if isinstance(item, dict))
