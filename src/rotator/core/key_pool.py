from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime
from typing import Any

from rotator.core.provider_config import (
    load_providers,
    get_model_rpd,
    get_model_rpm,
    get_provider_rpd,
)
from rotator.core.tracker import RPDTracker

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef,import-not-found]


POOL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "pool_data",
)


class KeyPool:
    def __init__(self, pool_dir: str = POOL_DIR):
        self._pool_dir = pool_dir
        self._pool_file = os.path.join(pool_dir, "key_pool.json")
        # Per-provider lock — google и openai выбирают ключи независимо
        self._locks: dict[str, asyncio.Lock] = {}
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
        self._states.setdefault(key, {"models": {}})

    def remove_key(self, key: str) -> bool:
        provider = self._key_provider.pop(key, None)
        if provider is None:
            return False
        if key in self._keys.get(provider, []):
            self._keys[provider].remove(key)
        self._states.pop(key, None)
        return True

    async def get_next_available_key(self, provider: str, model: str) -> str | None:
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
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
        lock = self._locks.get(self._key_provider.get(key, ""), asyncio.Lock())
        async with lock:
            state = self._get_model_state(key, model)
            state["exhausted"] = True
            state["cooldown_until"] = 0.0
            state["exhausted_day"] = self._today_str()
            self._save()

    async def mark_cooldown(self, key: str, model: str, seconds: int):
        lock = self._locks.get(self._key_provider.get(key, ""), asyncio.Lock())
        async with lock:
            state = self._get_model_state(key, model)
            state["cooldown_until"] = time.time() + seconds
            state["exhausted"] = True
            state.pop("exhausted_day", None)
            self._save()

    async def mark_success(self, key: str, model: str, tokens: int = 0):
        lock = self._locks.get(self._key_provider.get(key, ""), asyncio.Lock())
        async with lock:
            self._tracker.increment(key, model, tokens)
            state = self._get_model_state(key, model)
            state["exhausted"] = False
            state["cooldown_until"] = 0.0
            state.pop("exhausted_day", None)
            self._save()

    def get_remaining_rpd(self, key: str, model: str, provider: str) -> int:
        max_rpd = self._resolve_max_rpd(provider, model)
        return self._tracker.get_remaining(key, model, max_rpd)

    def get_remaining_rpm(self, key: str, model: str, provider: str) -> int:
        max_rpm = self._resolve_max_rpm(provider, model)
        if max_rpm is None:
            return 999
        return self._tracker.get_rpm_remaining(key, model, max_rpm)

    def get_stats(self, provider: str) -> dict[str, Any]:
        keys = self._keys.get(provider, [])
        result: dict[str, list[dict[str, Any]]] = {"keys": []}
        for key in keys:
            models_info = {}
            model_states = self._states.get(key, {}).get("models", {})

            # Объединяем модель-статусы из pool + tracker
            tracker_models = self._tracker._usage.get(key, {})
            all_models = set(model_states.keys()) | set(tracker_models.keys())

            for model in sorted(all_models):
                state = model_states.get(model) or {}
                max_rpd = self._resolve_max_rpd(provider, model) if model else 0
                remaining = self._tracker.get_remaining(
                    key, model, max_rpd
                ) if model else 0
                exhausted = state.get("exhausted", False) if state else False
                cooldown = state.get("cooldown_until", 0.0) if state else 0.0
                remaining_rpm = self.get_remaining_rpm(key, model, provider)
                models_info[model] = {
                    "exhausted": exhausted,
                    "cooldown_until": cooldown,
                    "remaining_rpd": remaining,
                    "max_rpd": max_rpd,
                    "remaining_rpm": remaining_rpm,
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
            # cooldown expired — снимаем exhausted
            state["exhausted"] = False
            state["cooldown_until"] = 0.0
            state.pop("exhausted_day", None)

        entry = self._tracker._get_entry(key, model)
        if self._tracker._should_reset(entry):
            # Новый день — сбрасываем любые exhausted
            if state.get("exhausted"):
                state["exhausted"] = False
                state.pop("exhausted_day", None)
            # Сбрасываем RPD через трекер
            self._tracker._reset_entry(entry)
            self._tracker._save()

        # RPD check — если исчерпан, помечаем exhausted до daily reset
        if max_rpd > 0 and entry.count >= max_rpd:
            state["exhausted"] = True
            state["cooldown_until"] = 0.0
            state["exhausted_day"] = self._today_str()
            return False

        # RPM check
        max_rpm = self._resolve_max_rpm_for_key(key, model)
        if max_rpm and self._tracker.get_rpm_remaining(key, model, max_rpm) <= 0:
            return False

        return True

    def _get_model_state(self, key: str, model: str) -> dict[str, Any]:
        key_states = self._states.setdefault(key, {})
        model_states = key_states.setdefault("models", {})
        return model_states.setdefault(model, {
            "exhausted": False,
            "cooldown_until": 0.0,
        })

    @staticmethod
    def _today_str() -> str:
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

    def _resolve_max_rpd(self, provider: str, model: str) -> int:
        try:
            providers = load_providers()
            model_rpd = get_model_rpd(providers, provider, model)
            if model_rpd is not None:
                return model_rpd
            return get_provider_rpd(providers, provider)
        except Exception:
            return 1500

    def _resolve_max_rpm(self, provider: str, model: str) -> int | None:
        try:
            providers = load_providers()
            return get_model_rpm(providers, provider, model)
        except Exception:
            return None

    def _resolve_max_rpm_for_key(self, key: str, model: str) -> int | None:
        provider = self._key_provider.get(key)
        if not provider:
            return None
        return self._resolve_max_rpm(provider, model)

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
