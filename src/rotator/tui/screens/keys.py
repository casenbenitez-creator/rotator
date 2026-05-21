from __future__ import annotations

from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from rotator.core.auth_bridge import write_auth_key


class KeysScreen(Screen):
    CSS_PATH = None

    _refresh_tick = reactive(0)  # type: ignore[valid-type]

    def compose(self):
        yield Header()
        yield Static("  Key Management", classes="dashboard-title")
        yield Static("", id="add-key-section")
        yield Input(placeholder="provider=key (e.g. google=...)", id="add-key-input")
        yield Static("", id="key-list-container", classes="key-list")
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

        container = self.query_one("#key-list-container", Static)
        lines = []
        for provider, stats in all_stats.items():
            lines.append(f"[bold]{provider}[/]")
            keys = stats.get("keys", [])
            if not keys:
                lines.append("  [italic]No keys[/]")
            for key_info in keys:
                key_masked = key_info["key"]
                for model_name, model_info in key_info.get("models", {}).items():
                    rpd = model_info.get("remaining_rpd", 0)
                    exhausted = model_info.get("exhausted", False)
                    if exhausted:
                        lines.append(
                            f"  [red]{key_masked} | {model_name}"
                            f" | RPD: {rpd} | EXHAUSTED[/]"
                        )
                    else:
                        lines.append(
                            f"  [green]{key_masked} | {model_name}"
                            f" | RPD: {rpd}[/]"
                        )
            lines.append("")

        placeholder = "  [italic]No keys loaded. Add one below.[/]"
        text = "\n".join(lines) if lines else placeholder
        container.update(text)

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "add-key-input":
            return

        text = event.value.strip()
        if "=" not in text:
            self.notify("Format: provider=key", severity="error")
            return

        provider, key = text.split("=", 1)
        provider = provider.strip()
        key = key.strip()

        if not provider or not key:
            self.notify("Provider and key cannot be empty", severity="error")
            return

        write_auth_key(provider, key)
        self.app.key_pool.add_key(provider, key)  # type: ignore[attr-defined]
        self.app.key_pool.save()  # type: ignore[attr-defined]

        self.notify(f"Added key for {provider}", severity="information")
        event.input.value = ""
        self._refresh_tick += 1
