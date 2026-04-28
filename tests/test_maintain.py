from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.maintain import build_maintenance_report, format_maintenance_report


def _write_config(tmp_path: Path, test_command: str) -> None:
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text(
        "\n".join(
            [
                "mode: balanced",
                "budget_per_task: 1.0",
                "models:",
                "  cheap: openai:gpt-4.1-nano",
                "  mid: openai:gpt-4.1-mini",
                "  premium: openai:gpt-4.1",
                "commands:",
                f'  test: "{test_command}"',
                '  lint: ""',
                "aegis:",
                '  base_url: "http://example.test"',
                "providers:",
                "  enabled: false",
                '  provider: "openai"',
                '  api_key_env: "OPENAI_API_KEY"',
                "patches:",
                "  generate_diff: false",
                "  max_context_chars: 12000",
                '  output_file: ".aegis/runs/latest.diff"',
            ]
        ),
        encoding="utf-8",
    )


def _write_latest_json(tmp_path: Path, payload: dict) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_maintain_unverified_repo(tmp_path: Path) -> None:
    report = build_maintenance_report(tmp_path)
    assert report["verification"]["status"] == "unavailable"
    assert "Add a test command to .aegis/aegis-code.yml to enable verified fixes." in report["suggestions"]


def test_maintain_verified_no_latest_run(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    report = build_maintenance_report(tmp_path)
    assert report["verification"]["status"] == "unknown"
    assert 'Run aegis-code "triage current test failures" to create a baseline report.' in report["suggestions"]


def test_maintain_latest_run_passing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    _write_latest_json(tmp_path, {"final_failures": {"failure_count": 0}})
    report = build_maintenance_report(tmp_path)
    assert report["verification"]["status"] == "passing"
    assert report["verification"]["failure_count"] == 0


def test_maintain_latest_run_failing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    _write_latest_json(tmp_path, {"final_failures": {"failure_count": 2}})
    report = build_maintenance_report(tmp_path)
    assert report["verification"]["status"] == "failing"
    assert report["verification"]["failure_count"] == 2
    assert "Run aegis-code fix to generate a supervised repair proposal." in report["suggestions"]


def test_maintain_uses_sll_from_latest_run(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    _write_latest_json(
        tmp_path,
        {
            "final_failures": {"failure_count": 0},
            "sll_analysis": {
                "available": True,
                "regime": "boundary",
                "collapse_risk": 0.1,
                "fragmentation_risk": 0.2,
                "drift_risk": 0.3,
                "stable_random_risk": 0.4,
            },
        },
    )
    report = build_maintenance_report(tmp_path)
    assert report["structure"]["sll_available"] is True
    assert report["structure"]["regime"] == "boundary"
    assert report["structure"]["risks"]["drift_risk"] == 0.3


def test_maintain_many_artifacts_and_backups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for i in range(21):
        (runs / f"r{i}.txt").write_text("x", encoding="utf-8")
    backups_root = tmp_path / ".aegis" / "backups"
    for i in range(11):
        snap = backups_root / f"20260101_0000{i:02d}"
        (snap / "a.py").parent.mkdir(parents=True, exist_ok=True)
        (snap / "a.py").write_text("x", encoding="utf-8")
    report = build_maintenance_report(tmp_path)
    assert "many_run_artifacts" in report["hygiene"]["issues"]
    assert "many_backups" in report["hygiene"]["issues"]


def test_maintain_formatter_sections(tmp_path: Path) -> None:
    report = build_maintenance_report(tmp_path)
    text = format_maintenance_report(report)
    assert "Repo health:" in text
    assert "Verification:" in text
    assert "Structure:" in text
    assert "Hygiene:" in text
    assert "Suggestions:" in text


def test_cli_maintain_prints_without_runtime(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no tests")))
    exit_code = cli.main(["maintain"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Repo health:" in out
