from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

from aegis_code import cli
from aegis_code.secrets import load_secrets


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = exc_type, exc, tb
        return False


def test_onboard_success(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    body = json.dumps(
        {
            "account_id": "acct_1",
            "api_key": "secret_key_value",
            "plan": "free",
            "limits": {},
        }
    )
    monkeypatch.setattr("aegis_code.onboard.urlopen", lambda *_args, **_kwargs: _FakeResponse(body))
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis onboarding complete." in out
    assert "API key saved locally." in out
    assert "Enhanced runtime remains opt-in. Enable aegis.enhanced_runtime in .aegis/aegis-code.yml when ready." in out
    assert "secret_key_value" not in out
    assert load_secrets(tmp_path).get("AEGIS_API_KEY") == "secret_key_value"


def test_onboard_network_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _raise(*_args, **_kwargs):
        raise OSError("network down")

    monkeypatch.setattr("aegis_code.onboard.urlopen", _raise)
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Onboarding failed: network_error" in out


def test_onboard_invalid_response(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.onboard.urlopen", lambda *_args, **_kwargs: _FakeResponse('{"plan":"free"}'))
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Onboarding failed: invalid_response" in out


def test_onboard_already_onboarded_409(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _raise(*_args, **_kwargs):
        body = b'{"detail":{"error":"already_onboarded"}}'
        raise HTTPError(
            url="https://example.test/v1/onboard",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr("aegis_code.onboard.urlopen", _raise)
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Onboarding failed: already_onboarded status=409" in out
    assert "api_key" not in out


def test_onboard_http_500(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _raise(*_args, **_kwargs):
        raise HTTPError(
            url="https://example.test/v1/onboard",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"failed"}'),
        )

    monkeypatch.setattr("aegis_code.onboard.urlopen", _raise)
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Onboarding failed: http_error status=500" in out


def test_onboard_422_validation_error(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _raise(*_args, **_kwargs):
        body = b'{"detail":{"error":"validation_error"}}'
        raise HTTPError(
            url="https://example.test/v1/onboard",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr("aegis_code.onboard.urlopen", _raise)
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Onboarding failed: validation_error status=422" in out


def test_onboard_prompt_for_email(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    body = json.dumps(
        {
            "account_id": "acct_1",
            "api_key": "secret_key_value",
            "plan": "free",
            "limits": {},
        }
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "user@example.com")
    monkeypatch.setattr("aegis_code.onboard.urlopen", lambda *_args, **_kwargs: _FakeResponse(body))
    exit_code = cli.main(["onboard"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis onboarding complete." in out
    assert "API key saved locally." in out
    assert "Enhanced runtime remains opt-in. Enable aegis.enhanced_runtime in .aegis/aegis-code.yml when ready." in out
    assert "secret_key_value" not in out
    assert load_secrets(tmp_path).get("AEGIS_API_KEY") == "secret_key_value"


def test_onboard_prompt_empty_email(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    exit_code = cli.main(["onboard"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Email is required." in out
