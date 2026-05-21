from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from textual.app import App
from textual.theme import Theme

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef,import-not-found]

from rotator.core.auth_bridge import load_auth_keys
from rotator.core.key_pool import KeyPool
from rotator.proxy.server import ProxyServer
from rotator.tui.screens.dashboard import DashboardScreen
from rotator.tui.screens.keys import KeysScreen
from rotator.tui.screens.proxy import ProxyScreen

THEME_DIR = os.path.join(os.path.dirname(__file__), "tui", "themes")


class RotatorApp(App):
    SCREENS = {
        "dashboard": DashboardScreen,
        "keys": KeysScreen,
        "proxy": ProxyScreen,
    }

    BINDINGS = [
        ("d", "switch_screen('dashboard')", "Dashboard"),
        ("k", "switch_screen('keys')", "Keys"),
        ("p", "switch_screen('proxy')", "Proxy"),
        ("t", "toggle_theme", "Toggle Theme"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.key_pool = KeyPool()
        self.proxy: ProxyServer | None = None
        self._theme_index = 0

    def on_mount(self):
        self._register_themes()
        self.theme = "dark"
        self._load_keys()
        self._start_proxy()
        self.push_screen("dashboard")

    def _register_themes(self):
        self.register_theme(Theme(
            name="dark",
            primary="#58A6FF",
            secondary="#1F6FEB",
            accent="#3FB950",
            background="#0D1117",
            surface="#161B22",
            error="#F85149",
            warning="#D29922",
            success="#3FB950",
        ))
        self.register_theme(Theme(
            name="light",
            primary="#0969DA",
            secondary="#0969DA",
            accent="#1A7F37",
            background="#FFFFFF",
            surface="#F6F8FA",
            error="#CF222E",
            warning="#9A6700",
            success="#1A7F37",
        ))

    @staticmethod
    def _detect_provider(key: str) -> str:
        if key.startswith("AIzaSy"):
            return "google"
        if key.startswith("sk-or-v1-") or key.startswith("sk-or-"):
            return "openrouter"
        if key.startswith("sk-"):
            return "openai"
        if key.startswith("nvapi-"):
            return "nvidia"
        if key.startswith("hf_"):
            return "huggingface"
        if key.startswith("fw_"):
            return "fireworks-ai"
        return "other"

    def _load_keys(self):
        gt_path = Path.home() / ".epub_translator" / "settings.json"
        if gt_path.is_file():
            try:
                with open(gt_path, encoding="utf-8") as f:
                    gt_data = json.load(f)
                raw_keys = gt_data.get(
                    "api_keys_with_status", gt_data.get("api_keys", [])
                )

                tz = ZoneInfo("America/Los_Angeles")
                now = datetime.now(tz)
                day_start = datetime(
                    now.year, now.month, now.day, 0, 1, 0, tzinfo=tz
                )
                day_start_ts = day_start.timestamp()
                now_ts = time.time()

                for item in raw_keys:
                    key = item["key"] if isinstance(item, dict) else item
                    if not key or not isinstance(key, str):
                        continue
                    prov = self._detect_provider(key.strip())
                    self.key_pool.add_key(prov, key.strip())

                    if not isinstance(item, dict):
                        continue

                    status_by_model = item.get("status_by_model", {})
                    for model_name, status in status_by_model.items():
                        if not model_name or model_name == "None":
                            continue
                        reqs = status.get("requests", [])

                        todays_count = sum(
                            1 for ts in reqs
                            if isinstance(ts, (int, float))
                            and ts >= day_start_ts
                        )
                        if todays_count > 0:
                            self.key_pool._tracker._import_usage(
                                key.strip(), model_name,
                                todays_count, day_start_ts,
                            )

                        recent = [
                            ts for ts in reqs
                            if isinstance(ts, (int, float))
                            and ts > now_ts - 60
                        ]
                        if recent:
                            rpm_dq = (
                                self.key_pool._tracker._rpm
                                .setdefault(key.strip(), {})
                                .setdefault(model_name, deque())
                            )
                            for ts in recent:
                                rpm_dq.append(ts)
            except Exception:
                pass

        keys_by_provider = load_auth_keys()
        for provider, keys in keys_by_provider.items():
            for key in keys:
                self.key_pool.add_key(provider, key)

    def _start_proxy(self):
        proxy = ProxyServer(pool=self.key_pool)
        self.proxy = proxy
        asyncio.create_task(proxy.start())

    def action_toggle_theme(self):
        themes = ["dark", "light"]
        self._theme_index = (self._theme_index + 1) % len(themes)
        self.theme = themes[self._theme_index]

    def action_switch_screen(self, screen_name: str):
        self.push_screen(screen_name)

    async def on_shutdown(self):
        if self.proxy:
            await self.proxy.stop()
