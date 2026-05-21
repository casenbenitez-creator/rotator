# AGENTS.md — opencode Key Rotator

Local reverse-proxy + TUI for rotating API keys across multiple providers (Gemini, OpenAI, OpenRouter, etc.) in opencode. Automatic failover on 429/403, RPD-aware key pool, dynamic themes.

## Commands

- `pip install -e .` — install in dev mode
- `python start.py` — launch TUI (or `python -m rotator`)
- `python start.py --proxy-only` — headless proxy (no TUI)
- `ruff check src/` — lint (mandatory after every edit)
- `python -m py_compile <file>` — syntax check

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Textual TUI (src/rotator/tui/)                 │
│  ├─ dashboard.py      — главный экран           │
│  ├─ keys.py           — управление пулом ключей │
│  ├─ proxy.py          — статус/лог прокси       │
│  └─ themes/           — dark.tcss, light.tcss   │
├─────────────────────────────────────────────────┤
│  Proxy (src/rotator/proxy/)                     │
│  ├─ server.py         — aiohttp reverse proxy   │
│  └─ router.py         — маршрутизация           │
│     /google/v1beta/*  → generativelanguage...   │
│     /openai/v1/*      → api.openai.com          │
│     /openrouter/*     → openrouter.ai           │
├─────────────────────────────────────────────────┤
│  Core (src/rotator/core/)                       │
│  ├─ key_pool.py       — пул ключей + RPD трекинг│
│  ├─ provider_config.py— загрузка api_providers  │
│  ├─ auth_bridge.py    — чтение/запись auth.json │
│  └─ tracker.py        — RPD/RPM счётчики        │
└─────────────────────────────────────────────────┘
         │
         ▼
opencode —baseURL→ http://localhost:8484/google/...
```

## Agent Roles

| Role | File | Scope |
|------|------|-------|
| Backend Engineer | `.opencode/agents/backendengineer.md` | `src/rotator/core/` + `src/rotator/proxy/` |
| Frontend Engineer | `.opencode/agents/frontendengineer.md` | `src/rotator/tui/` — экраны, виджеты, темы |

Activate by telling the agent which role to assume; it reads the corresponding `.opencode/agents/` file.

## Operational Boundaries

### ALWAYS
- Run `ruff check src/` after every edit
- Read `api_providers.json` from existing GeminiTranslator config before hardcoding any model limits
- Use `asyncio` for all I/O (proxy + RPD tracking)
- Validate keys with a real API call before marking them active
- Save key pool state atomically (temp file + `os.replace()`)

### NEVER
- Commit secrets, API keys, or `.env` files
- Hardcode RPD/RPM limits — load from `api_providers.json`
- Hardcode colors — all styling via Textual CSS variables
- Block the asyncio event loop with sync file I/O
- Add emoji characters in code or UI
- Add comments unless explicitly asked

### ASK FIRST
- New provider integrations beyond Gemini/OpenAI/OpenRouter
- Changes to the proxy routing protocol (URL path schema)
- Breaking changes to the key pool data format
- New dependencies with broad impact

## Critical Rules

### 1. Proxy Must Be Stateless Per-Request

The proxy receives a request, picks a key, forwards, returns. No session state, no per-connection key pinning. Only exception: failed requests (429) mutate the key's exhaustion status.

```python
# CORRECT
async def handle_request(self, request):
    key = await self.pool.get_next_available_key(provider, model)
    if key is None:
        return aiohttp.web.Response(status=503, text="No available keys")
    try:
        return await self._forward(request, key)
    except RateLimitError:
        await self.pool.mark_exhausted(key, model)
        key = await self.pool.get_next_available_key(provider, model)
        if key:
            return await self._forward(request, key)
        return aiohttp.web.Response(status=429)
```

### 2. RPD Tracking — Daily Reset с Timezone

Gemini free tier RPD сбрасывается в полночь по `America/Los_Angeles`. В `api_providers.json` уже есть `reset_policy`:
```json
"reset_policy": {
  "type": "daily",
  "timezone": "America/Los_Angeles",
  "reset_hour": 0,
  "reset_minute": 1
}
```
Ровно эту логику и используем. Никакой другой.

### 3. Key Pool — Atomic Persistence

```python
# CORRECT — temp file + replace
import os, json, tempfile

def _save_pool(self):
    fd, tmp = tempfile.mkstemp(dir=self._pool_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(self._serialize(), f, indent=2)
        os.replace(tmp, self._pool_file)
    except:
        os.unlink(tmp)
        raise
```

### 4. Textual CSS Variables — Единственный способ стилизации

```python
# CORRECT
from textual.app import App
from textual.theme import Theme

app.register_theme(Theme(
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

# WRONG — inline styles
widget.styles.background = "#0D1117"
```

## Coding Standards

- Python 3.10+, asyncio, aiohttp
- `ruff` for linting (no flake8/pylint)
- `os.replace()` for atomic file writes
- `aiohttp.ClientSession` for all HTTP calls (one session per proxy instance)
- Textual CSS for all UI styling
- Type hints on all public functions
- `from __future__ import annotations` for forward references

## Theme System

### Textual Themes

Themes are defined as `Textual Theme` objects and switched via `app.theme = "name"`.

Available themes: `dark`, `light`, `dracula`, `nord`.

Theme CSS files live in `src/rotator/tui/themes/{name}.tcss` and are loaded per-theme:

```python
# CORRECT
app.register_theme(Theme(
    name="dracula",
    primary="#BD93F9",
    secondary="#6272A4",
    ...
))
app.theme = "dracula"  # auto-loads themes/dracula.tcss
```

### Textual CSS Naming

| CSS Class | Purpose | Used In |
|-----------|---------|---------|
| `.key-card` | Карточка ключа с RPD | `dashboard.py`, `keys.py` |
| `.key-card.green` | Ключ активен | |
| `.key-card.yellow` | Temporary pause | |
| `.key-card.red` | Исчерпан | |
| `.provider-header` | Заголовок провайдера | `dashboard.py` |
| `.stats-panel` | Панель статистики | `dashboard.py` |
| `.proxy-log` | Лог прокси | `proxy.py` |

## Context & Memory

- **AGENTS.md** — living document; propose updates for recurring gotchas
- **PROJECT_MAP.md** — will be created when project structure stabilises

## Common Pitfalls

1. **aiohttp `ClientSession` must be reused** — creating a new session per request leaks connections. Create once in proxy startup, close on shutdown.
2. **Textual `compose()` vs `on_mount()`** — `compose()` builds the static widget tree; `on_mount()` is for async data loading. Never do I/O in `compose()`.
3. **Key pool race conditions** — multiple concurrent requests can exhaust the same key simultaneously. Use `asyncio.Lock` around key selection + exhaustion.
4. **`os.replace()` on Windows** — fails if target exists and is open. Use `tempfile.mkstemp()` in same directory + `os.replace()`.
5. **Gemini API key header** — Google uses `x-goog-api-key`, not `Authorization`. Proxy must handle both.
6. **OpenAI baseURL trailing `/v1`** — `@ai-sdk/openai` appends paths to baseURL. If baseURL is `http://localhost:8484/openai/v1`, the SDK sends `POST /openai/v1/chat/completions` — which is correct.
7. **Textual CSS variable fallback** — TCSS uses `$primary` etc. If you rename a variable, all themes break. Keep theme variable names stable across theme files.

## Project Map

```
C:\Users\user\Desktop\ai\rotator\
├── AGENTS.md                         ← этот файл
├── .opencode/
│   ├── .gitignore
│   └── agents/
│       ├── backendengineer.md
│       └── frontendengineer.md
├── src/
│   └── rotator/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py                    ← Textual App
│       ├── tui/
│       │   ├── __init__.py
│       │   ├── screens/
│       │   │   ├── __init__.py
│       │   │   ├── dashboard.py
│       │   │   ├── keys.py
│       │   │   └── proxy.py
│       │   ├── widgets/
│       │   │   ├── __init__.py
│       │   │   ├── key_card.py
│       │   │   └── provider_header.py
│       │   └── themes/
│       │       ├── dark.tcss
│       │       └── light.tcss
│       ├── proxy/
│       │   ├── __init__.py
│       │   ├── server.py
│       │   └── router.py
│       └── core/
│           ├── __init__.py
│           ├── key_pool.py
│           ├── provider_config.py
│           ├── auth_bridge.py
│           └── tracker.py
├── pyproject.toml
└── README.md
```
