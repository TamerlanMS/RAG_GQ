# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

RAG assistant for GQ Group (electrical-equipment supplier, Kazakhstan). A FastAPI service backed by
Postgres + Pinecone that answers product questions (price / stock / articul lookup), creates orders and
notifies managers over Telegram, serves Telegram and WhatsApp client bots, imports supplier price
lists from `.xlsx`, and serves a manager web console that mirrors WhatsApp conversations.
Code comments, prompts and user-facing strings are in Russian — keep them Russian.

## Commands

Local (Poetry, Python 3.10–3.13):

```bash
poetry install && poetry run pip install aiogram httpx openpyxl xlrd
```

```bash
poetry run uvicorn src.main:app --reload --port 8000
```

```bash
poetry run pytest tests/ -q
```

Single test: `poetry run pytest tests/test_main.py::test_ping -q` (the only test is currently commented
out; `pytest` is not declared in `pyproject.toml` — install it explicitly).

Lint / types (pre-commit config pins these; run them the same way):

```bash
poetry run pre-commit run --all-files
```

Frontend (manager console) — dev server with a proxy to the API on :8000:

```bash
cd frontend && npm install && npm run dev
```

Docker (the deployment path — see `README.md`). The image has a Node stage that builds `frontend/`
into `/srv/console`, so a console change needs `--build`, not `restart`:

```bash
docker compose up -d --build
```

Compose starts `postgres` (host port **54321**) and `api` (bound to `127.0.0.1:8000`), overriding
`DB_HOST=postgres` and `INTERNAL_API_URL=http://api:8000`. The repo is bind-mounted into `/app`, so
`docker compose restart api` picks up code changes without a rebuild.

Convert a 1C `.xls` export into the `/update_DB` payload:

```bash
python scripts/xls_to_import.py export.xls products_import.json
```

## Architecture

### Two independent LLM paths

This is the single most important thing to know before changing anything LLM-related:

1. **LangGraph ReAct agent** — `src/common/tools/ReAct_agent.py`. A `StateGraph` (agent ↔ ToolNode loop)
   over `LLM` from `src/common/llm_model.py`, with tools that hit Postgres and Pinecone
   (`smart_search`, `search_by_name`, `search_by_articul`, `search_by_brand`, `create_order`, …).
   Exposed **only** via `POST /api/v1/ask`, keyed by `thread_id` (the client's phone number).
   History lives in an `InMemorySaver` — process-local, lost on restart.
2. **The bots** — `src/telegram_bot/bot.py` and `src/whatsapp_bot/whatsapp.py`. These do **not** call the
   agent. Each calls `gpt-4o` directly (httpx / `AsyncOpenAI`) with `src/settings/system_prompt.txt` and
   its own in-memory history dict, **without tools** — so bot answers have no live price/stock data.
   Escalation to managers is keyword-based (`_TRIGGER_KEYWORDS`, `_ESCALATION_PHRASES`, duplicated in
   both files — keep them in sync).

A change to product search only affects the bots if it goes through `/ask`.

### Request/data flow

- `src/main.py` — lifespan runs `Base.metadata.create_all` (no Alembic migrations are actually used
  despite the dependency), starts the aiogram polling bot, mounts `src/api/v1/endpoints.py` and the
  WhatsApp webhook router under `/api/v1`. FastAPI docs are disabled (`docs_url=None`).
- Product truth lives in Postgres (`products` table, `src/db/Models/product_models.py`). All product
  fields except `id` are **strings** — prices and quantities are stored as text exactly as imported.
  `name` is the unique key used for upserts.
- `POST /api/v1/update_DB` (`update_db` in `src/db/CRUD.py`) is the bulk pipeline: parse the
  `{"Date":…, "Products":[…]}` payload → dedupe by `name` → `INSERT … ON CONFLICT (name) DO UPDATE` in
  batches of 500 → trim whitespace → **rebuild both Pinecone indexes from the DB**. Pinecone is
  therefore a derived cache; the DB is authoritative.
- `src/common/vector_store.py` holds two Pinecone singletons, `vector_store` (names, namespace `names`)
  and `articul_store` (articuls, namespace `articuls`). `is_articul()` heuristically routes a query
  between them: ≤30 chars, <3 Cyrillic letters, >50% latin/digits, and must contain a digit or a
  separator (so bare words like `DKC`/`Lezard` count as brands, not articuls).

### Manager web console (`/console`)

A React+Vite SPA in `frontend/` that mirrors WhatsApp conversations for managers, plus its API in
`src/api/v1/console.py` (prefix `/api/v1/console`). Three things about it are load-bearing:

- **It uses a SEPARATE database.** `src/db/chat_database.py` defines its own `ChatBase`, `chat_engine`
  and `ChatSessionLocal` pointing at `CHAT_DB_NAME` (default `gq_chat`). `managers`, `chats` and
  `chat_messages` live there — never register them on the main `Base`, or `DELETE /api/v1/drop_DB`
  (`Base.metadata.drop_all`) would wipe client correspondence. `ensure_chat_database()` creates the DB
  at startup (needed because `POSTGRES_DB` makes only one, and `/docker-entrypoint-initdb.d/` scripts
  never run on an existing `pgdata/`). All three tables must stay together: Postgres has no cross-database FKs.
- **Persistence hooks live in `src/whatsapp_bot/whatsapp.py`, asymmetrically.** Inbound is one
  `chat_store.save_message` call at the very top of `_process_message`, *before* any branching — that
  single insert covers all four early-return paths. Outbound is written inside `_send_whatsapp` /
  `_send_whatsapp_buttons` after `raise_for_status()`, so the console never shows as delivered
  something that wasn't. `WHATSAPP_DRY_RUN=true` skips the Gupshup call but still persists.
- **Takeover gates the bot.** `Chat.is_taken_over` is checked in `_process_message` right after the
  inbound insert; when set, the bot returns early (and adds the phone to `_greeted`, or releasing the
  chat would re-trigger the first-contact welcome menu mid-conversation).

`src/common/chat_store.py` is the only writer. Its sync core runs via `asyncio.to_thread` (SQLAlchemy is
sync here, and the loop already hosts aiogram polling plus 30-45s OpenAI calls), every path is wrapped so
persistence can never break the bot, and `is_taken_over` fails **open** — a DB outage must not silence
the bot for every client at once. Chat identity is `(channel, external_id)`; for WhatsApp `external_id`
is the **raw** Gupshup number that goes into `destination`, while `phone` is the normalized `+7…` form
used only for search — never send to `Chat.phone`.

Real-time is short polling with an `after_id` cursor (chats 5s, thread 3s), not SSE/WebSocket: it
self-heals across restarts and survives a topology change. Auth is bcrypt + JWT signed with `API_TOKEN`;
seed managers with `docker compose exec api python scripts/seed_managers.py`.

Phone normalization lives in `src/common/phone.py` (`normalize_phone`) and is the single source of
truth — `check_phone_number` in `ReAct_agent.py` delegates to it. Do not reimplement it: three of the
five phones in `config.MANAGERS` are written as `+8…`, and the old inline version returned `None` for
all of them plus for raw Gupshup numbers.

### Graceful degradation

Optional subsystems are wrapped so the app still boots when they're missing — preserve this pattern:

- Pinecone unreachable → `vector_store`/`articul_store` are `None`; every caller must null-check.
- `aiogram` missing or `TELEGRAM_INPUT_BOT_TOKEN` unset → `start_bot()` returns early.
- `src/whatsapp_bot` import failure → the WhatsApp router simply isn't mounted (`main.py`).
- `src/supplier_parser` import failure → the `/suppliers/*` endpoints' dependencies are `None`
  (`endpoints.py`) — note those routes then fail at call time, not import time.
- Built console missing → `main.py` checks `is_dir()` before `app.mount`, since `StaticFiles` on a
  missing directory raises at startup.

One gap in this pattern: `start_bot()` guards only an *empty* `TELEGRAM_INPUT_BOT_TOKEN`. A non-empty
but invalid token makes aiogram raise `TokenValidationError` out of `lifespan` and takes down the whole
API. To run without the Telegram bot, leave the variable empty rather than filling in a placeholder.

### Telegram: two bots, one flow

`TELEGRAM_INPUT_BOT_TOKEN` is the *client-facing* bot (aiogram polling, inline-keyboard menus).
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` is the *notification* bot used by
`src/common/telegram_notifier.py` to push orders/escalations to managers. Incoming messages are
debounced (`DEBOUNCE_SECONDS`) and batched per user under a per-user `asyncio.Lock` so a second batch
can't read history before the first writes it. Manager routing lives in `src/settings/config.py`
(`MANAGERS`, `MANAGER_CHAT_IDS`); while `TELEGRAM_TEST_MODE=true` **everything** goes to
`TELEGRAM_TEST_CHAT_ID`.

### WhatsApp

Gupshup in Meta Cloud API v3 format. `GET /api/v1/whatsapp/webhook` handles both the `hub.challenge`
verification and Gupshup's bare 200-OK health check; `POST` returns 200 immediately and processes in the
background. First text from an unknown number gets the welcome button menu instead of a GPT reply
(`_greeted` set, in memory). Send URL is `https://api.gupshup.io/wa/api/v1/msg` (`/wa/`, not `/sm/`).

### Supplier price import

`src/supplier_parser/` is a self-contained two-phase pipeline, separate from the `products` table:

`detector.detect_supplier` (sheet names + cell probes, never the filename) → `registry.get_parser` →
per-supplier parser → `models.SupplierProduct` (pydantic, normalizes article/name/price) →
`diff_engine.build_diff` against `supplier_catalog` → `importer.confirm_import` writes
`supplier_catalog` + `price_history` + `import_log`.

API is two-step: `POST /suppliers/upload` returns a preview and stashes the diff in the **in-process**
`_pending_imports` dict keyed by `"{supplier_code}:{file_name}"`; `POST /suppliers/confirm` applies it.
This state does not survive a restart and does not work across multiple workers.

To add a supplier: new `BaseParser` subclass in `src/supplier_parser/parsers/`, register it in
`registry._REGISTRY`, and add a signature branch to `detector.detect_supplier`.

## Configuration

`src/settings/config.py` raises at import time if `OPENAI_API_KEY` or `API_TOKEN` is missing, and reads
`src/settings/system_prompt.txt` (required — it is the agent and bot persona). `src/settings/db_settings.py`
requires all five `DB_*` vars. `.env` is gitignored; `.env.example` is the template but is **incomplete** —
it omits the `GUPSHUP_*` and `TG_CHAT_ID_*` variables that the code reads.

Dependency gotcha: `aiogram`, `httpx`, `openpyxl` (and `xlrd` for the script) are **not** in
`pyproject.toml` — the Dockerfile `pip install`s them separately. Add new runtime deps to `pyproject.toml`
and keep `poetry.lock` in sync rather than extending that `pip install` line. Poetry isn't on the host;
run `docker compose exec api poetry lock` after editing `pyproject.toml`, then `up -d --build` —
`restart` picks up source via the bind-mount but not new `site-packages`.

`.env` gotcha: `docker compose`'s `env_file` does **not** strip inline `#` comments — `KEY=value  # note`
puts the whole string, comment included, into the variable. Keep every explanation on its own line.
