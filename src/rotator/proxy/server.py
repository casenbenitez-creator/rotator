from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import re
import time
from typing import Any, Callable, Optional

import aiohttp
from aiohttp import web

from rotator.core.key_pool import KeyPool
from rotator.proxy.router import ProxyRouter

logger = logging.getLogger("rotator.proxy")

OnRequestLogged = Callable[[dict[str, Any]], None] | None


class ProxyServer:
    def __init__(
        self,
        pool: KeyPool,
        router: ProxyRouter | None = None,
        host: str = "127.0.0.1",
        port: int = 8484,
    ):
        self._pool = pool
        self._router = router or ProxyRouter()
        self._host = host
        self._port = port
        self._session: Optional[aiohttp.ClientSession] = None
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self.on_request_logged: OnRequestLogged = None

    async def start(self):
        self._session = aiohttp.ClientSession()
        self._app = web.Application()

        self._app.router.add_route("*", "/{tail:.*}", self._handle)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        logger.info("Proxy listening on %s:%s", self._host, self._port)

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        if self._session:
            await self._session.close()

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        start = time.monotonic()
        path = request.path

        routed = self._router.route(path)
        if routed is None:
            return web.json_response(
                {"error": f"No route for path: {path}"},
                status=404,
            )

        provider, upstream_url, _prefix = routed

        key = await self._pool.get_next_available_key(provider, self._infer_model(path))
        if key is None:
            self._log_request(request, provider, None, 503, start)
            return web.json_response(
                {"error": "No available keys for provider", "provider": provider},
                status=503,
            )

        status, body = await self._forward_with_failover(
            request, provider, upstream_url, key,
        )
        self._log_request(request, provider, key, status, start)

        return web.Response(body=body, status=status, content_type=None)

    async def _forward_with_failover(
        self,
        request: web.Request,
        provider: str,
        upstream_url: str,
        key: str,
    ) -> tuple[int, bytes]:
        headers = self._prepare_headers(request, provider, key)
        body = await request.read()
        method = request.method

        for attempt in range(2):
            try:
                async with self._session.request(
                    method,
                    upstream_url,
                    headers=headers,
                    data=body,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    resp_body = await resp.read()
                    status = resp.status

                    if status == 429:
                        model = self._infer_model(request.path)
                        cooldown = self._parse_retry_after(resp, resp_body)
                        if cooldown:
                            await self._pool.mark_cooldown(key, model, cooldown)
                        else:
                            await self._pool.mark_exhausted(key, model)
                        if attempt == 0:
                            new_key = await self._pool.get_next_available_key(
                                provider, model,
                            )
                            if new_key and new_key != key:
                                key = new_key
                                headers = self._prepare_headers(request, provider, key)
                                continue
                        return status, resp_body

                    if status == 403:
                        model = self._infer_model(request.path)
                        await self._pool.mark_exhausted(key, model)
                        return status, resp_body

                    if status < 500:
                        model = self._infer_model(request.path)
                        await self._pool.mark_success(key, model)

                    return status, resp_body

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Request failed: %s", exc)
                if attempt == 0:
                    model = self._infer_model(request.path)
                    await self._pool.mark_exhausted(key, model)
                    new_key = await self._pool.get_next_available_key(
                        provider, model,
                    )
                    if new_key and new_key != key:
                        key = new_key
                        headers = self._prepare_headers(request, provider, key)
                        continue
                return 502, str(exc).encode()

        return 502, b"Upstream request failed"

    def _prepare_headers(
        self,
        request: web.Request,
        provider: str,
        key: str,
    ) -> dict[str, str]:
        headers = dict(request.headers)
        headers.pop("Host", None)
        headers = self._router.strip_auth_headers(headers)
        headers = self._router.inject_key(provider, headers, key)
        return headers

    @staticmethod
    def _infer_model(path: str) -> str:
        parts = path.rstrip("/").split("/")
        if len(parts) >= 4 and parts[-2] == "models":
            return parts[-1]
        for i, part in enumerate(parts):
            if part == "models" and i + 1 < len(parts):
                return parts[i + 1]
        return "unknown"

    @staticmethod
    def _parse_retry_after(
        resp: aiohttp.ClientResponse, body: bytes
    ) -> int | None:
        # 1. Retry-After header (секунды)
        val = resp.headers.get("Retry-After")
        if val:
            try:
                return int(val)
            except ValueError:
                pass

        # 2. Gemini: поле retryDelay в JSON-теле
        if body:
            try:
                data = jsonlib.loads(body)
                details = (
                    data.get("error", {})
                    .get("details", [])
                )
                for detail in details:
                    delay = detail.get("retryDelay", "")
                    if delay:
                        match = re.search(r"(\d+)", delay)
                        if match:
                            return int(match.group(1))
            except (jsonlib.JSONDecodeError, AttributeError):
                pass

        return None

    def _log_request(
        self,
        request: web.Request,
        provider: str,
        key: str | None,
        status: int,
        start: float,
    ):
        elapsed = time.monotonic() - start
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "method": request.method,
            "path": request.path,
            "provider": provider,
            "status": status,
            "elapsed": f"{elapsed:.3f}s",
        }
        if self.on_request_logged:
            self.on_request_logged(entry)


async def run_proxy(
    host: str = "127.0.0.1",
    port: int = 8484,
):
    from rotator.core.auth_bridge import load_auth_keys

    pool = KeyPool()
    keys_by_provider = load_auth_keys()
    for provider, keys in keys_by_provider.items():
        pool.load_keys(provider, keys)

    server = ProxyServer(pool=pool, host=host, port=port)
    await server.start()

    logger.info("Proxy running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()
