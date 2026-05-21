from __future__ import annotations

import asyncio
import os

from textual.app import App
from textual.theme import Theme

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

    def _load_keys(self):
        # 1. Загружаем ключи из pool-файла (уже сделано в KeyPool.__init__)
        # 2. Дополняем из auth.json (не затираем существующие)
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
