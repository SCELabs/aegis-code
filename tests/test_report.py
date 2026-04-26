from __future__ import annotations

from pathlib import Path

from aegis_code.report import write_reports


def test_report_generation_writes_json_and_md(tmp_path: Path) -> None:
    payload = {
        "task": "example task",
        "mode": "balanced",
        "dry_run": True,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {"budget": {"pressure": "low"}},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["src", "tests"]},
        "commands_run": [],
        "status": "dry_run_planned",
        "notes": ["planning only"],
    }
    paths = write_reports(payload, cwd=tmp_path)
    assert paths["json"].exists()
    assert paths["md"].exists()
    assert "Aegis Code Run Report" in paths["md"].read_text(encoding="utf-8")
