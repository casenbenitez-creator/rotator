from __future__ import annotations

from typing import Any

ROUTES: list[tuple[str, str, str]] = [
    ("/google/", "google", "https://generativelanguage.googleapis.com"),
    ("/openai/", "openai", "https://api.openai.com"),
    ("/openrouter/", "openrouter", "https://openrouter.ai"),
]


class ProxyRouter:
    def __init__(self, routes: list[tuple[str, str, str]] | None = None):
        self._routes = routes or ROUTES

    def route(self, path: str) -> tuple[str, str, str] | None:
        for prefix, provider, upstream in self._routes:
            if path.startswith(prefix):
                remaining = path[len(prefix):]
                if not remaining.startswith("/"):
                    remaining = "/" + remaining
                upstream_url = upstream + remaining
                return provider, upstream_url, prefix
        return None

    def inject_key(
        self, provider: str, headers: dict[str, Any], key: str
    ) -> dict[str, Any]:
        headers = dict(headers)
        if provider == "google":
            headers["x-goog-api-key"] = key
            headers.pop("Authorization", None)
        else:
            headers["Authorization"] = f"Bearer {key}"
            headers.pop("x-goog-api-key", None)
        return headers

    def strip_auth_headers(self, headers: dict[str, Any]) -> dict[str, Any]:
        headers = dict(headers)
        headers.pop("Authorization", None)
        headers.pop("x-goog-api-key", None)
        return headers
