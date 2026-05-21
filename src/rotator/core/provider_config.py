from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROVIDERS_PATH = Path(
    "C:/Users/user/Desktop/ai/GeminiTranslator v11.0"
    " by Mankhar/config/api_providers.json"
)


def load_providers(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = DEFAULT_PROVIDERS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_models_for_provider(
    providers: dict[str, Any], provider_name: str
) -> dict[str, Any]:
    provider = providers.get(provider_name, {})
    return {k: v for k, v in provider.items() if isinstance(v, dict)}


def get_reset_policy(provider: dict[str, Any]) -> dict[str, Any]:
    return provider.get(
        "reset_policy",
        {"type": "daily", "timezone": "America/Los_Angeles"},
    )


def get_model_limits(model_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "rpd": model_config.get("rpd"),
        "rpm": model_config.get("rpm"),
        "tpm": model_config.get("tpm"),
        "context_length": model_config.get("context_length"),
        "thinking_level": model_config.get("thinking_level"),
    }
