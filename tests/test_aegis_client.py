from __future__ import annotations

from aegis_code.aegis_client import AegisBackendClient


class _FakeResult:
    model_tier = "premium"
    context_mode = "broad"
    max_retries = 3
    allow_escalation = True
    execution = {"budget": {"pressure": "medium"}}


class _FakeAutoClient:
    def __init__(self) -> None:
        self.last_kwargs = None

    def step(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResult()


class _FakeSdkClient:
    def __init__(self) -> None:
        self.auto_client = _FakeAutoClient()

    def auto(self):
        return self.auto_client


def test_aegis_backend_client_uses_auto_step(monkeypatch) -> None:
    fake_sdk = _FakeSdkClient()
    monkeypatch.setattr(AegisBackendClient, "_build_sdk_client", lambda _self: fake_sdk)
    client = AegisBackendClient(api_key="x", base_url="https://example.com")

    decision = client.step_scope(
        step_name="aegis_code_task",
        step_input={"task": "test"},
        symptoms=["unstable_workflow"],
        severity="medium",
        metadata={"budget_total": 1.0},
    )

    assert fake_sdk.auto_client.last_kwargs is not None
    assert set(fake_sdk.auto_client.last_kwargs.keys()) == {
        "step_name",
        "step_input",
        "symptoms",
        "severity",
        "metadata",
    }
    assert decision.model_tier == "premium"
    assert decision.context_mode == "broad"
    assert decision.max_retries == 3
    assert decision.allow_escalation is True
    assert decision.execution == {"budget": {"pressure": "medium"}}
