from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_PROVIDERS_PATH = Path(
    "C:/Users/user/Desktop/ai/GeminiTranslator v11.0"
    " by Mankhar/config/api_providers.json"
)

# Маппинг: имя провайдера в URL -> имя в api_providers.json
PROVIDER_ALIASES: dict[str, str] = {
    "google": "gemini",
    "openai": "openai",
    "openrouter": "openrouter",
}


def load_providers(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = DEFAULT_PROVIDERS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_provider_config(
    providers: dict[str, Any], alias: str
) -> dict[str, Any]:
    real_name = PROVIDER_ALIASES.get(alias, alias)
    return providers.get(real_name, {})


def get_models_for_provider(
    providers: dict[str, Any], alias: str
) -> dict[str, Any]:
    provider = get_provider_config(providers, alias)
    models = provider.get("models", {})
    if not models:
        models = {k: v for k, v in provider.items() if isinstance(v, dict)}
    return models


def find_model_config(
    providers: dict[str, Any], alias: str, model_name: str
) -> dict[str, Any]:
    models = get_models_for_provider(providers, alias)
    # Сначала по display name (exact match)
    if model_name in models:
        return models[model_name]
    # Потом по model id
    for display_name, cfg in models.items():
        if isinstance(cfg, dict) and cfg.get("id") == model_name:
            return cfg
    # Потом частичное совпадение
    for display_name, cfg in models.items():
        if isinstance(cfg, dict) and (
            display_name.lower() in model_name.lower()
            or model_name.lower() in display_name.lower()
        ):
            return cfg
    return {}


def get_provider_rpd(providers: dict[str, Any], alias: str) -> int:
    provider = get_provider_config(providers, alias)
    return provider.get("rpd", 1500)


def get_model_rpd(
    providers: dict[str, Any], alias: str, model_name: str
) -> int | None:
    cfg = find_model_config(providers, alias, model_name)
    return cfg.get("rpd") if cfg else None


def get_reset_policy(providers: dict[str, Any], alias: str) -> dict[str, Any]:
    provider = get_provider_config(providers, alias)
    return provider.get(
        "reset_policy",
        {"type": "daily", "timezone": "America/Los_Angeles"},
    )
