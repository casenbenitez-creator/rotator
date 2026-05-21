from __future__ import annotations

from textual.widgets import Static


class ProviderHeader(Static):
    def __init__(self, name: str, key_count: int = 0, **kwargs):
        self._provider_name = name
        self._key_count = key_count
        super().__init__(**kwargs)

    def on_mount(self):
        self._render()

    def update_count(self, count: int):
        self._key_count = count
        self._render()

    def _render(self):
        text = f"  {self._provider_name}"
        if self._key_count > 0:
            text += f"  [{self._key_count} keys]"
        self.update(text)
