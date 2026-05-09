from __future__ import annotations

import types

from aegis_code.tools.shell import run_shell_command


def test_run_shell_command_windows_uses_shell_execution(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("aegis_code.tools.shell.sys.platform", "win32")
    monkeypatch.setattr("aegis_code.tools.shell.subprocess.run", _fake_run)
    result = run_shell_command(name="test", command="npm test", cwd=tmp_path)

    assert result.status == "ok"
    assert result.exit_code == 0
    assert seen["args"] == ("npm test",)
    assert bool(seen["kwargs"].get("shell")) is True

