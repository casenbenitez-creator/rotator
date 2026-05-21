from __future__ import annotations

import json
import os
import tempfile
import time
from collections import deque
from datetime import datetime
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef,import-not-found]


class UsageEntry:
    def __init__(self, count: int = 0, token_count: int = 0, window_start: float = 0.0):
        self.count = count
        self.token_count = token_count
        self.window_start = window_start

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "token_count": self.token_count,
            "window_start": self.window_start,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageEntry:
        return cls(
            count=data.get("count", 0),
            token_count=data.get("token_count", 0),
            window_start=data.get("window_start", 0.0),
        )


class RPDTracker:
    def __init__(self, pool_dir: str | os.PathLike):
        self._pool_dir = os.fspath(pool_dir)
        self._usage_file = os.path.join(self._pool_dir, "usage.json")
        self._usage: dict[str, dict[str, UsageEntry]] = {}
        # RPM rolling window (in-memory only): key -> model -> deque of timestamps
        self._rpm: dict[str, dict[str, deque[float]]] = {}
        self._load()

    # ---- RPD (daily) ----

    def get_remaining(self, key: str, model: str, max_rpd: int) -> int:
        entry = self._get_entry(key, model)
        if self._should_reset(entry):
            return max_rpd
        return max(0, max_rpd - entry.count)

    def increment(self, key: str, model: str, tokens: int = 0):
        entry = self._get_entry(key, model)
        if self._should_reset(entry):
            self._reset_entry(entry)
        entry.count += 1
        entry.token_count += tokens
        self._save()
        self._increment_rpm(key, model)

    def _get_entry(self, key: str, model: str) -> UsageEntry:
        model_usage = self._usage.setdefault(key, {})
        if model not in model_usage:
            model_usage[model] = UsageEntry(window_start=self._now_timestamp())
        return model_usage[model]

    @staticmethod
    def _should_reset(entry: UsageEntry) -> bool:
        if entry.window_start == 0.0:
            return True
        tz = ZoneInfo("America/Los_Angeles")
        reset_time = datetime.fromtimestamp(entry.window_start, tz=tz)
        now = datetime.now(tz)
        next_reset = reset_time.replace(hour=0, minute=1, second=0, microsecond=0)
        if now >= next_reset:
            return True
        return False

    def _reset_entry(self, entry: UsageEntry):
        entry.count = 0
        entry.token_count = 0
        entry.window_start = self._now_timestamp()

    @staticmethod
    def _now_timestamp() -> float:
        return datetime.now(ZoneInfo("America/Los_Angeles")).timestamp()

    # ---- RPM (rolling 60s) ----

    def get_rpm_remaining(self, key: str, model: str, max_rpm: int) -> int:
        self._prune_rpm(key, model)
        dq = self._get_rpm_deque(key, model)
        return max(0, max_rpm - len(dq))

    def _get_rpm_deque(self, key: str, model: str) -> deque[float]:
        return self._rpm.setdefault(key, {}).setdefault(model, deque())

    def _prune_rpm(self, key: str, model: str):
        dq = self._get_rpm_deque(key, model)
        cutoff = time.time() - 60
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _increment_rpm(self, key: str, model: str):
        dq = self._get_rpm_deque(key, model)
        dq.append(time.time())
        # Короткое окно 60с, не храним больше 200
        if len(dq) > 200:
            self._prune_rpm(key, model)

    # ---- persistence ----

    def _load(self):
        if os.path.isfile(self._usage_file):
            try:
                with open(self._usage_file, encoding="utf-8") as f:
                    raw = json.load(f)
                for key, models in raw.items():
                    for model, data in models.items():
                        model_usage = self._usage.setdefault(key, {})
                        model_usage[model] = UsageEntry.from_dict(data)
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self):
        fd, tmp = tempfile.mkstemp(dir=self._pool_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                serialized = {
                    key: {model: entry.to_dict() for model, entry in models.items()}
                    for key, models in self._usage.items()
                }
                json.dump(serialized, f, indent=2)
            os.replace(tmp, self._usage_file)
        except Exception:
            os.unlink(tmp)
            raise
