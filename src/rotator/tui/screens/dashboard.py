from __future__ import annotations

from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class DashboardScreen(Screen):
    CSS_PATH = None

    _refresh_tick = reactive(0)  # type: ignore[valid-type]

    def compose(self):
        yield Header()
        yield Static("  Key Pool Dashboard", classes="dashboard-title")
        yield Static("", id="stats-summary", classes="stats-panel")
        yield Static("", id="provider-container")
        yield Footer()

    def on_mount(self):
        self.set_interval(2.0, self._tick)

    def _tick(self):
        self._refresh_tick += 1

    def watch__refresh_tick(self, _value: int):
        self._refresh()

    def _refresh(self):
        pool = self.app.key_pool  # type: ignore[attr-defined]
        all_stats = pool.get_all_stats()

        total_keys = 0
        active_keys = 0
        provider_names = list(all_stats.keys())

        for provider, stats in all_stats.items():
            total_keys += len(stats.get("keys", []))
            for key_info in stats.get("keys", []):
                for model_info in key_info.get("models", {}).values():
                    if not model_info.get("exhausted", False):
                        active_keys += 1

        stats_summary = self.query_one("#stats-summary", Static)
        stats_summary.update(
            f"  Providers: {len(provider_names)}"
            f"  |  Total keys: {total_keys}"
            f"  |  Active: {active_keys}"
        )

        container = self.query_one("#provider-container", Static)
        lines = []
        for provider in provider_names:
            stats = all_stats[provider]
            lines.append(f"[bold]{provider}[/]")
            for key_info in stats.get("keys", []):
                key_masked = key_info["key"]
                models = key_info.get("models", {})
                if not models:
                    lines.append(f"  {key_masked} [italic]awaiting first request[/]")
                else:
                    for model_name, model_info in models.items():
                        if not model_name:
                            continue
                        rpd = model_info.get("remaining_rpd", 0)
                        max_rpd = model_info.get("max_rpd", 1500)
                        exhausted = model_info.get("exhausted", False)
                        label = (
                            f"  {key_masked} | {model_name}"
                            f" | RPD: {rpd}/{max_rpd}"
                        )
                        if exhausted or rpd <= 0:
                            label = f"[red]{label} EXHAUSTED[/]"
                        lines.append(label)
            lines.append("")

        container.update("\n".join(lines) if lines else "  [italic]No keys loaded[/]")
