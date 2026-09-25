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
- **Takeover auto-releases after `TAKEOVER_AUTO_RELEASE_MINUTES`** (default 20) **of manager
  inactivity.** `Chat.taken_over_at` does double duty: `POST /chats/{id}/takeover` sets it, and
  `POST /chats/{id}/reply` in `console.py` re-stamps it on every successful send — so it's really
  "last manager activity," not just "moment of takeover" (repurposed rather than adding a column,
  since `create_all` never runs `ALTER TABLE`). A background loop in `main.py`'s `lifespan`
  (`_takeover_watchdog`, checks every 60s) calls `chat_store.release_stale_takeovers()`, which clears
  `is_taken_over` on anything past the cutoff and drops a system message naming who went quiet. The
  first check runs immediately at startup, so takeovers that went stale while the container was down
  get swept right away.

`src/common/chat_store.py` is the only writer. Its sync core runs via `asyncio.to_thread` (SQLAlchemy is
sync here, and the loop already hosts aiogram polling plus 30-45s OpenAI calls), every path is wrapped so
persistence can never break the bot, and `is_taken_over` fails **open** — a DB outage must not silence
the bot for every client at once. Chat identity is `(channel, external_id)`; for WhatsApp `external_id`
is the **raw** Gupshup number that goes into `destination`, while `phone` is the normalized `+7…` form
used only for search — never send to `Chat.phone`.

**Attachments are downloaded to disk, not linked.** Gupshup media URLs expire and need the apikey, so
`_process_message` downloads every image/video/audio/document/sticker right after the inbound insert
(before the takeover gate — managers need the file most when they hold the chat) and
`src/common/media_store.py` writes it to `MEDIA_DIR` (default `/app/media` = `./media` on the host,
gitignored — back it up alongside `pgdata/`). The path/MIME/size are merged into
`chat_messages.extra` by `chat_store.attach_media` — note empty `extra` is JSON `null`, not SQL NULL,
so the merge uses `jsonb_typeof`, not `COALESCE`. The console serves files via
`GET /console/media/{id}?exp&sig` — an HMAC-signed URL (secret `API_TOKEN`), not JWT, because
`<img>/<video>` can't send `Authorization`. Client-supplied MIME is untrusted: only images/video/audio/PDF
are served inline; everything else is forced to `attachment` + `application/octet-stream`, all with
`CSP: sandbox`. The same downloaded bytes are reused for Vision and the Telegram forward.

Outgoing files (`POST /console/chats/{id}/reply-file`) go the other way: Gupshup only accepts a URL, so
the upload is saved to `MEDIA_DIR` and Gupshup gets a 1-hour path-signed `/console/media-out` link on
`PUBLIC_BASE_URL` or `https://$DOMAIN` — signed by path, not message id, because the message row is
written only after Gupshup accepts. Voice notes recorded in the console (`voice=true`) are **always re-encoded** by
**ffmpeg** (installed in the Dockerfile) to mono OGG/Opus — the only format WhatsApp shows as a voice note;
browsers record WebM (Chrome/Firefox) or MP4 (Safari). Never remux the browser stream with `-c:a copy`:
that produced OGG with `preskip=0` and 2.5 ms packets which play on desktop but show "This audio is no
longer available" on the recipient's iPhone. Encoding settings are profiles in
`media_store.VOICE_PROFILES`, chosen by `VOICE_PROFILE`; `scripts/voice_variants.py <phone>` sends the
same recording in every profile so the one that plays on iPhone can be picked. Recording needs a secure context (https or
localhost), and nginx must allow large bodies (`client_max_body_size`).

Real-time is short polling with an `after_id` cursor (chats 5s, thread 3s), not SSE/WebSocket: it
self-heals across restarts and survives a topology change. Auth is bcrypt + JWT signed with `API_TOKEN`;
seed managers with `docker compose exec api python scripts/seed_managers.py`.

Phone normalization lives in `src/common/phone.py` (`normalize_phone`) and is the single source of
truth — `check_phone_number` in `ReAct_agent.py` delegates to it. Do not reimplement it: the old inline
version silently returned `None` for the `+8…`-style numbers some managers had and for raw Gupshup
numbers; `config.MANAGERS` phones are now stored in canonical `+7…` form.

**`GET /console/stats` is director-only** — the first (and so far only) role check in the codebase.
`require_director` (`src/common/auth.py`) compares `manager.code == "director"`, not `manager.role`:
`code` is the stable slug from `config.MANAGERS`, while `role` is display text ("Руководитель") that
could be edited without meaning to change permissions. The frontend mirrors the same check
(`manager.code === "director"` in `Console.jsx`) to hide the "Статистика" button/tab entirely for
everyone else — the API check is what actually enforces it, the UI check just avoids showing a
control that would 403. A "заявка" (request) here is just a `Chat` row — no new table. Stats are
computed live over `chats`/`chat_messages` for a period (`today`/`week`/`month`/`all`, or explicit
`date_from`/`date_to` overriding it): total chats created, how many still have `unread_count > 0`,
how many have zero `ChatMessage` rows with `author='manager'` ("never replied"), and a per-manager
breakdown of distinct chats each replied in — built with a double `LEFT JOIN` so managers with zero
activity still show up with `0` rather than being absent from the list.

### Auth on `endpoints.py` and the WhatsApp webhook

All mutating/expensive routes in `src/api/v1/endpoints.py` require `Depends(get_current_manager)`
(same JWT as the console): `/ask`, `/create_DB`, `/drop_DB`, `/cleanup_spaces`, the three `/products`
mutations, and all three `/suppliers/*` routes. Read-only routes (`/status_DB`, `GET /products*`,
`GET /suppliers`) stay open. **`POST /update_DB` is the one exception** — it also accepts an
`X-Service-Token` header checked against `SERVICE_API_TOKEN` (`require_manager_or_service_token` in
`src/common/auth.py`), because bulk price import is normally run by a script/cron, not from a logged-in
browser. If `SERVICE_API_TOKEN` is unset the route is manager-only by construction (an empty string
never passes the `hmac.compare_digest` check).

The WhatsApp webhook (`POST /api/v1/whatsapp/webhook`) requires `?token=<GUPSHUP_VERIFY_TOKEN>` in the
query string — same variable already used for the GET `hub.verify_token` handshake. On mismatch it logs
a warning and still returns `200 OK` (not 403), matching the existing behavior for malformed JSON/missing
`entry[]` in that handler — don't reveal to a scanner that the URL is live, and don't trigger Gupshup
retries. **This means the Callback URL registered in the Gupshup dashboard must include the token as a
query param**, or real inbound messages get silently dropped after deploy — the request still 200s, so
nothing looks wrong in logs or monitoring. `tests/integration/*.py` and `scripts/send_test_message.py`
already append `?token=...` (reading `GUPSHUP_VERIFY_TOKEN`, same default `"gqgroup_verify"`) — keep any
new webhook caller consistent with that.

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
