from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from typing import Any

from rotator.core.provider_config import load_providers, get_models_for_provider
from rotator.core.tracker import RPDTracker


POOL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "pool_data",
)


class KeyPool:
    def __init__(self, pool_dir: str = POOL_DIR):
        self._pool_dir = pool_dir
        self._pool_file = os.path.join(pool_dir, "key_pool.json")
        self._lock = asyncio.Lock()
        self._tracker = RPDTracker(pool_dir)

        # provider -> list of keys in round-robin order
        self._keys: dict[str, list[str]] = {}
        # provider -> current round-robin index
        self._rr_index: dict[str, int] = {}
        # key -> model -> state
        self._states: dict[str, dict[str, dict[str, Any]]] = {}
        # key -> provider mapping (reverse lookup)
        self._key_provider: dict[str, str] = {}

        self._load()

    # ---- public API ----

    def load_keys(self, provider: str, keys: list[str]):
        self._keys[provider] = list(dict.fromkeys(keys))  # deduplicate, preserve order
        self._rr_index.setdefault(provider, 0)
        for key in keys:
            self._key_provider[key] = provider
            self._states.setdefault(key, {})

    def add_key(self, provider: str, key: str):
        if provider not in self._keys:
            self._keys[provider] = []
        if key not in self._keys[provider]:
            self._keys[provider].append(key)
        self._key_provider[key] = provider
        self._states.setdefault(provider, {}).setdefault(key, {"models": {}})

    def remove_key(self, key: str) -> bool:
        provider = self._key_provider.pop(key, None)
        if provider is None:
            return False
        if key in self._keys.get(provider, []):
            self._keys[provider].remove(key)
        self._states.pop(key, None)
        return True

    async def get_next_available_key(self, provider: str, model: str) -> str | None:
        async with self._lock:
            keys = self._keys.get(provider)
            if not keys:
                return None

            max_rpd = self._resolve_max_rpd(provider, model)
            n = len(keys)
            for _ in range(n):
                idx = self._rr_index.get(provider, 0) % n
                self._rr_index[provider] = (idx + 1) % n

                key = keys[idx]
                if self._is_available(key, model, max_rpd):
                    return key
            return None

    async def mark_exhausted(self, key: str, model: str):
        async with self._lock:
            state = self._get_model_state(key, model)
            state["exhausted"] = True
            self._save()

    async def mark_cooldown(self, key: str, model: str, seconds: int):
        async with self._lock:
            state = self._get_model_state(key, model)
            state["cooldown_until"] = time.time() + seconds
            state["exhausted"] = True
            self._save()

    async def mark_success(self, key: str, model: str, tokens: int = 0):
        async with self._lock:
            self._tracker.increment(key, model, tokens)
            state = self._get_model_state(key, model)
            state["exhausted"] = False
            state["cooldown_until"] = 0.0
            self._save()

    def get_remaining_rpd(self, key: str, model: str, provider: str) -> int:
        max_rpd = self._resolve_max_rpd(provider, model)
        return self._tracker.get_remaining(key, model, max_rpd)

    def get_stats(self, provider: str) -> dict[str, Any]:
        keys = self._keys.get(provider, [])
        result: dict[str, list[dict[str, Any]]] = {"keys": []}
        for key in keys:
            states = self._states.get(key, {})
            models_info = {}
            for model, state in states.items():
                models_info[model] = {
                    "exhausted": state.get("exhausted", False),
                    "cooldown_until": state.get("cooldown_until", 0.0),
                    "remaining_rpd": self.get_remaining_rpd(key, model, provider),
                }
            result["keys"].append({
                "key": self._mask_key(key),
                "models": models_info,
            })
        return result

    def get_all_stats(self) -> dict[str, Any]:
        result = {}
        for provider in self._keys:
            result[provider] = self.get_stats(provider)
        return result

    def save(self):
        self._save()

    # ---- internal ----

    def _is_available(self, key: str, model: str, max_rpd: int) -> bool:
        state = self._get_model_state(key, model)
        if state.get("exhausted", False):
            cooldown_until = state.get("cooldown_until", 0.0)
            if cooldown_until > time.time():
                return False
            state["exhausted"] = False
            state["cooldown_until"] = 0.0

        remaining = self._tracker.get_remaining(key, model, max_rpd)
        return remaining > 0

    def _get_model_state(self, key: str, model: str) -> dict[str, Any]:
        key_states = self._states.setdefault(key, {})
        model_states = key_states.setdefault("models", {})
        return model_states.setdefault(model, {
            "exhausted": False,
            "cooldown_until": 0.0,
        })

    def _resolve_max_rpd(self, provider: str, model: str) -> int:
        try:
            providers = load_providers()
            models = get_models_for_provider(providers, provider)
            model_config = models.get(model, {})
            return model_config.get("rpd", 1500)
        except Exception:
            return 1500

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return key[:4] + "****"
        return key[:6] + "****" + key[-4:]

    def _serialize(self) -> dict[str, Any]:
        return {
            "keys": self._keys,
            "rr_index": self._rr_index,
            "states": self._states,
        }

    def _deserialize(self, data: dict[str, Any]):
        self._keys = data.get("keys", {})
        self._rr_index = data.get("rr_index", {})
        self._states = data.get("states", {})
        for provider, keys in self._keys.items():
            for key in keys:
                self._key_provider[key] = provider

    def _load(self):
        if not os.path.isfile(self._pool_file):
            return
        try:
            with open(self._pool_file, encoding="utf-8") as f:
                data = json.load(f)
            self._deserialize(data)
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self):
        os.makedirs(self._pool_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._pool_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._serialize(), f, indent=2)
            os.replace(tmp, self._pool_file)
        except Exception:
            os.unlink(tmp)
            raise
