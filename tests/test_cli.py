from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.models import AegisDecision


class FakeAegisClient:
    def step_scope(self, **_: object) -> AegisDecision:
        return AegisDecision(
            model_tier="cheap",
            context_mode="focused",
            max_retries=1,
            allow_escalation=False,
            execution={"budget": {"pressure": "low"}},
            note="fake",
        )


def test_cli_init_creates_project_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["init"])
    assert exit_code == 0
    assert (tmp_path / ".aegis" / "aegis-code.yml").exists()
    assert (tmp_path / ".aegis" / "project_model.md").exists()


def test_cli_dry_run_writes_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.runtime.client_from_env", lambda _base_url: FakeAegisClient())
    exit_code = cli.main(["plan release notes", "--dry-run"])
    assert exit_code == 0
    assert (tmp_path / ".aegis" / "runs" / "latest.json").exists()
    assert (tmp_path / ".aegis" / "runs" / "latest.md").exists()


def test_cli_accepts_propose_patch_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.runtime.client_from_env", lambda _base_url: FakeAegisClient())
    exit_code = cli.main(["plan release notes", "--dry-run", "--propose-patch"])
    assert exit_code == 0


def test_cli_check_sll_does_not_run_runtime(monkeypatch) -> None:
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    monkeypatch.setattr("aegis_code.cli.check_sll_available", lambda: {"available": False, "import_path": "structural_language_lab", "error": "x"})
    exit_code = cli.main(["--check-sll"])
    assert exit_code == 0
