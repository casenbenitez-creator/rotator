from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_AUTH_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"


def load_auth_keys(path: str | Path | None = None) -> dict[str, list[str]]:
    if path is None:
        path = DEFAULT_AUTH_PATH
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    result: dict[str, list[str]] = {}
    for provider, entry in raw.items():
        if isinstance(entry, dict) and "key" in entry:
            result.setdefault(provider, []).append(entry["key"])
    return result


def write_auth_key(
    provider: str,
    key: str,
    path: str | Path | None = None,
):
    if path is None:
        path = DEFAULT_AUTH_PATH

    existing: dict[str, Any] = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

    existing[provider] = {"type": "api", "key": key}

    directory = os.path.dirname(os.fspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, os.fspath(path))
    except Exception:
        os.unlink(tmp)
        raise


def remove_auth_key(
    provider: str,
    path: str | Path | None = None,
) -> bool:
    if path is None:
        path = DEFAULT_AUTH_PATH
    if not os.path.isfile(path):
        return False

    with open(path, encoding="utf-8") as f:
        existing = json.load(f)

    if provider not in existing:
        return False

    del existing[provider]

    directory = os.path.dirname(os.fspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp, os.fspath(path))
    except Exception:
        os.unlink(tmp)
        raise
    return True
