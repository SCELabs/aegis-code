from aegis_code.config import default_config
from aegis_code.routing import normalize_tier, resolve_model_for_tier


def test_routing_cheap_model() -> None:
    cfg = default_config()
    assert resolve_model_for_tier(cfg, "cheap") == "openai:gpt-4.1-nano"


def test_routing_defaults_to_mid() -> None:
    cfg = default_config()
    assert normalize_tier("weird-tier") == "mid"
    assert resolve_model_for_tier(cfg, "weird-tier") == "openai:gpt-4.1-mini"
