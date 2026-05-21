from __future__ import annotations

from typing import Any

from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class ProxyScreen(Screen):
    CSS_PATH = None

    _log_entries: list[str] = []
    _refresh_tick = reactive(0)  # type: ignore[valid-type]

    def compose(self):
        yield Header()
        yield Static("  Proxy Log", classes="dashboard-title")
        yield Static("", id="proxy-status", classes="stats-panel")
        yield Static("", id="log-container", classes="proxy-log")
        yield Footer()

    def on_mount(self):
        self._log_entries = []
        self._last_log_count = 0
        proxy = getattr(self.app, "proxy", None)
        if proxy:
            proxy.on_request_logged = self._on_log
        self.set_interval(1.0, self._tick)

    def _on_log(self, entry: dict[str, Any]):
        line = (
            f"[{entry.get('time', '')}] "
            f"{entry.get('method', '')} "
            f"{entry.get('path', '')} "
            f"-> {entry.get('provider', '')} "
            f"[{entry.get('status', '')}] "
            f"({entry.get('elapsed', '')})"
        )
        entry_status = entry.get("status", 200)
        if entry_status >= 400:
            line = f"[red]{line}[/]"
        elif entry_status >= 300:
            line = f"[yellow]{line}[/]"
        else:
            line = f"[green]{line}[/]"

        self._log_entries.append(line)
        if len(self._log_entries) > 1000:
            self._log_entries = self._log_entries[-500:]

    def _tick(self):
        self._refresh_tick += 1

    def watch__refresh_tick(self, _value: int):
        self._refresh()

    def _refresh(self):
        status_widget = self.query_one("#proxy-status", Static)
        proxy = getattr(self.app, "proxy", None)
        if proxy:
            status_widget.update(
                f"  Proxy: running  |  Log entries: {len(self._log_entries)}"
            )
        else:
            status_widget.update("  Proxy: [yellow]not started[/]")

        log_widget = self.query_one("#log-container", Static)
        if self._log_entries:
            display = "\n".join(self._log_entries[-50:])
            log_widget.update(display)
        else:
            log_widget.update("  [italic]Waiting for requests...[/]")
