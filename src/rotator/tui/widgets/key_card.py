from __future__ import annotations

from textual.widgets import Static


class KeyCard(Static):
    def __init__(
        self,
        key: str,
        rpd_remaining: int = 0,
        rpd_max: int = 1500,
        status: str = "active",
        model: str = "",
        **kwargs,
    ):
        self._key = key
        self._rpd_remaining = rpd_remaining
        self._rpd_max = rpd_max
        self._status = status
        self._model = model
        super().__init__(**kwargs)

    def on_mount(self):
        self._apply_css()
        self._render()

    def update(
        self,
        rpd_remaining: int | None = None,
        status: str | None = None,
    ):
        if rpd_remaining is not None:
            self._rpd_remaining = rpd_remaining
        if status is not None:
            self._status = status
        self._apply_css()
        self._render()

    def _apply_css(self):
        if self._status == "exhausted" or self._rpd_remaining <= 0:
            self.classes = "key-card red"
        elif self._rpd_remaining < self._rpd_max * 0.2:
            self.classes = "key-card yellow"
        else:
            self.classes = "key-card green"

    def _render(self):
        parts = [f"  {self._key}"]
        if self._model:
            parts.append(f"model: {self._model}")
        parts.append(f"RPD: {self._rpd_remaining}/{self._rpd_max}")
        if self._status == "exhausted":
            parts.append("EXHAUSTED")
        self.update(" | ".join(parts))
