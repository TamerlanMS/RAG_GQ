# Деплой на bot.gqe-online.kz

Инструкция для переноса того, что сделано в ветке `feature/frontend`
(веб-консоль менеджеров, защита эндпоинтов, таймер автовозврата, статистика
по заявкам), на продовый сервер под доменом `bot.gqe-online.kz`.

## Что уже готово, трогать не нужно

- Домен `gqe-online.kz` зарегистрирован, DNS управляется через ps.kz.
- Запись `bot.gqe-online.kz → A → 89.218.93.198` уже существует в зоне —
  никаких изменений в панели PS.kz не требуется.
- На `89.218.93.198`, судя по всему, уже развёрнут этот проект и работает
  Telegram-бот через `aiogram`-polling — ему домен не был нужен, потому что
  polling не принимает входящих HTTP-запросов. Ничего в его конфигурации
  этот деплой не меняет.

## Что добавляется

Порт `api` в `docker-compose.yaml` слушает только `127.0.0.1:8010` — снаружи
контейнера недоступен. WhatsApp-вебхуку (Gupshup обязан достучаться по
HTTPS) и веб-консоли нужен публичный адрес с TLS. Для этого в
`docker-compose.yaml` добавлен сервис `caddy` (обратный прокси, сам
получает и продлевает сертификат Let's Encrypt — вручную ничего настраивать
не нужно, кроме открытых портов 80/443 и правильного DNS, который уже есть).

Сервис `caddy` помечен `profiles: ["prod"]` — обычный `docker compose up -d`
его не поднимает (ни у вас локально, ни случайно на сервере). Запускается
только явным `docker compose --profile prod up -d`.

---

## Часть 1 — локально (на этой машине)

`master` не трогаем — всё остаётся в `feature/frontend`, просто отправляем
её на GitHub:

```bash
git push origin feature/frontend
```

## Часть 2 — на сервере (SSH на 89.218.93.198)

### 2.1. Переключиться на feature/frontend

```bash
cd /путь/к/проекту   # там же, где уже лежит текущий деплой
git fetch origin
git checkout feature/frontend 2>/dev/null || git checkout -b feature/frontend origin/feature/frontend
git pull origin feature/frontend
```

(вторая строка сама разберётся: если локально такой ветки ещё нет —
создаст и привяжет к `origin/feature/frontend`, если уже есть — просто
переключится).

### 2.2. Добавить новые переменные в СУЩЕСТВУЮЩИЙ `.env`

Не пересоздавайте `.env` — в нём уже настоящие `OPENAI_API_KEY`,
`TELEGRAM_INPUT_BOT_TOKEN` и т.д. Допишите в конец только то, чего там ещё
нет (сверить полный список — `.env.example`):

```bash
cat >> .env <<'EOF'

# ─── Консоль менеджеров ───────────────────────────────────
API_TOKEN=CHANGE_ME_RANDOM_64_CHARS
SERVICE_API_TOKEN=
CHAT_DB_NAME=gq_chat
CONSOLE_JWT_TTL_HOURS=12
CONSOLE_DIST_DIR=/srv/console
TAKEOVER_AUTO_RELEASE_MINUTES=20

# ─── WhatsApp (Gupshup) — заполнить реальными значениями ──
GUPSHUP_API_KEY=
GUPSHUP_APP_NAME=GQGroup
GUPSHUP_SOURCE_PHONE=
GUPSHUP_VERIFY_TOKEN=CHANGE_ME_RANDOM_SECRET
WHATSAPP_DRY_RUN=false

# ─── Обратный прокси ───────────────────────────────────────
DOMAIN=bot.gqe-online.kz
ACME_EMAIL=ваш-реальный-email@пример
EOF
```

Обязательно сгенерировать случайные значения вместо `CHANGE_ME_...`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # для API_TOKEN
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # для GUPSHUP_VERIFY_TOKEN
```

`API_TOKEN` — это ещё и секрет подписи JWT консоли (см. `CLAUDE.md`), должен
быть длинным и случайным. `GUPSHUP_VERIFY_TOKEN` — секрет вебхука, он же
понадобится в шаге 2.5.

Если раньше в `.env` уже была строка `DB_PORT=...` — проверьте, что это
просто число (`5432`), без пояснений в той же строке: `docker compose`
не обрезает `# комментарий` после значения.

### 2.3. Открыть порты 80/443

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

(если используется не `ufw`, а провайдерский firewall/security group — открыть
там; 8010 наружу открывать не нужно, он и так только на 127.0.0.1).

### 2.4. Запустить

```bash
docker compose up -d --build
docker compose --profile prod up -d caddy
```

Первая команда пересоберёт и перезапустит `api` (краткий даунтайм Telegram-бота
на пересборку — это нормально) и поднимет `postgres`. Вторая — обратный прокси.

Проверить, что сертификат выпустился:

```bash
docker compose logs caddy --tail 30
```

Ищите `certificate obtained successfully` — если вместо этого ошибки ACME,
см. раздел «Если не получилось» ниже.

### 2.5. Проверка

```bash
curl -s https://bot.gqe-online.kz/api/v1/status_DB
```

Должен вернуть JSON с версией Postgres, без ошибок сертификата.

Создать менеджеров (пароли выводятся один раз, сохраните их):

```bash
docker compose exec api python scripts/seed_managers.py
```

Открыть `https://bot.gqe-online.kz/console/` в браузере, войти по телефону
и выведенному паролю.

### 2.6. Обновить Callback URL в кабинете Gupshup

В настройках приложения Gupshup укажите:

```
https://bot.gqe-online.kz/api/v1/whatsapp/webhook?token=<значение GUPSHUP_VERIFY_TOKEN из .env>
```

**Без токена в конце адреса реальные сообщения от клиентов будут молча
отбрасываться** (вебхук всегда отвечает `200 OK`, ошибки нигде не будет
видно) — см. раздел про безопасность в `CLAUDE.md`.

Отправьте тестовое сообщение боту в WhatsApp и убедитесь, что оно появилось
в `https://bot.gqe-online.kz/console/`.

---

## Если не получилось (ACME)

- Сертификат не выпускается → проверьте, что `curl http://bot.gqe-online.kz`
  снаружи (не с самого сервера) действительно доходит до этой машины —
  провайдер мог заблокировать 80/443 отдельно от `ufw`.
- `too many certificates already issued` — Let's Encrypt лимитирует по
  5 попыток на домен в неделю; если тестировали конфиг несколько раз подряд,
  подождите или временно используйте `acme_ca https://acme-staging-v02.api.letsencrypt.org/directory`
  в `Caddyfile` для тестов (staging-сертификаты браузер не примет, но лимит
  не расходуется).

## Безопасность — стоит сделать отдельно

- `docker-compose.yaml` публикует Postgres на `54321:5432` — на публичном
  сервере имеет смысл убрать это наружу (оставить доступ только изнутри
  Docker-сети) или закрыть порт файрволом, если прямой доступ к БД снаружи
  не нужен.
- Пароли, которые выведет `seed_managers.py`, — временные. Смените их через
  `POST /api/v1/console/me/password` после первого входа.
- `SERVICE_API_TOKEN` можно оставить пустым, если массовый импорт прайса
  всегда делается через консоль — тогда `/update_DB` останется доступен
  только вошедшим менеджерам.

## Обновления после первого деплоя

Дальше — обычный цикл (сервер уже стоит на `feature/frontend`):

```bash
git pull origin feature/frontend
docker compose up -d --build
```

`caddy` трогать не нужно (сертификат уже выпущен и живёт в volume
`caddy_data`, `docker compose up -d --build` его не пересоздаёт).
