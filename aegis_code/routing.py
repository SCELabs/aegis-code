from __future__ import annotations

from aegis_code.models import AppConfig

VALID_TIERS = {"cheap", "mid", "premium"}


def normalize_tier(tier: str | None) -> str:
    if tier in VALID_TIERS:
        return str(tier)
    return "mid"


def resolve_model_for_tier(config: AppConfig, tier: str | None) -> str:
    normalized = normalize_tier(tier)
    if normalized == "cheap":
        return config.models.cheap
    if normalized == "premium":
        return config.models.premium
    return config.models.mid
