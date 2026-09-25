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

Порт `api` в `docker-compose.yaml` слушает только `127.0.0.1:8000` — снаружи
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

`master` не трогаем — всё остаётся в `feature/frontend` (уже запушена на
GitHub). Загрузить на сервер готовый продовый `.env.production` под именем
`.env.new` — старый `.env` пока НЕ перезаписываем (PowerShell):

```powershell
scp .env.production root@89.218.93.198:/путь/к/проекту/.env.new
```

## Часть 2 — на сервере (SSH на 89.218.93.198)

### 2.0. Осмотреться и сделать бэкап

```bash
cd /путь/к/проекту   # там же, где уже лежит текущий деплой
docker compose ps
git status --short
sudo ss -tlnp | grep -E ':(80|443) '
```

- `git status` должен быть пустым (кроме `.env.new`) — иначе `git checkout`
  ниже откажется переключать ветку; локальные правки на сервере сначала
  сохранить (`git stash`) или разобраться, что это.
- Если `ss` что-то показал на 80/443 (nginx, apache, другой прокси) —
  его нужно остановить/перенастроить, иначе `caddy` не поднимется.

Бэкап (нужен для отката, см. конец файла):

```bash
cp .env .env.backup
docker compose exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER"' > backup-$(date +%F).sql
git rev-parse --abbrev-ref HEAD > .branch.backup
```

### 2.1. Переключиться на feature/frontend

```bash
git fetch origin
git checkout feature/frontend 2>/dev/null || git checkout -b feature/frontend origin/feature/frontend
git pull origin feature/frontend
```

(вторая строка сама разберётся: если локально такой ветки ещё нет —
создаст и привяжет к `origin/feature/frontend`, если уже есть — просто
переключится).

### 2.2. Подставить новый `.env`

`.env.new` уже содержит все переменные (консоль, Gupshup, `DOMAIN`, случайный
`API_TOKEN`), но две группы значений ОБЯЗАНЫ совпадать со старым серверным
`.env`:

- `DB_USER` / `DB_PASS` / `DB_NAME` — Postgres применяет их только при первой
  инициализации `pgdata/`; с другими значениями `api` просто не подключится
  к уже существующей базе.
- `PINECONE_*` — в `.env.production` они пустые; если на сервере были
  заполнены, перенести (иначе поиск через `/ask` деградирует).

Сравнить, не показывая значения:

```bash
for k in DB_HOST DB_PORT DB_USER DB_PASS DB_NAME PINECONE_API_KEY PINECONE_NAMES_INDEX_HOST PINECONE_ARTICUL_INDEX_HOST TELEGRAM_INPUT_BOT_TOKEN TELEGRAM_BOT_TOKEN; do
  a=$(grep "^$k=" .env.backup | cut -d= -f2-); b=$(grep "^$k=" .env.new | cut -d= -f2-)
  [ "$a" = "$b" ] && echo "OK       $k" || echo "РАЗЛИЧИЕ $k"
done
```

Затем `nano .env.new`:

- для каждого `РАЗЛИЧИЕ` по `DB_*` и `PINECONE_*` — взять значение из `.env.backup`;
- `ACME_EMAIL` — вписать настоящий email (с placeholder'ом `caddy`
  упадёт на старте: `wrong argument count ... after 'email'`);
- `WHATSAPP_DRY_RUN=false`;
- ни одна строка не должна иметь `# комментарий` после значения —
  `docker compose` не обрезает его и он попадёт в переменную
  (особенно опасно для `TELEGRAM_INPUT_BOT_TOKEN`: невалидный токен роняет
  всё приложение при старте).

Проверить, что нет дублей ключей (должно быть пусто), и подставить:

```bash
grep -oE '^[A-Z_]+=' .env.new | sort | uniq -d
mv .env.new .env
```

`GUPSHUP_VERIFY_TOKEN` из этого файла понадобится в шаге 2.6.

### 2.3. Открыть порты 80/443

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

(если используется не `ufw`, а провайдерский firewall/security group — открыть
там; 8000 наружу открывать не нужно, он и так только на 127.0.0.1).

### 2.4. Запустить

```bash
docker compose up -d --build
docker compose --profile prod up -d caddy
```

Первая команда пересоберёт и перезапустит `api` (краткий даунтайм Telegram-бота
на пересборку — это нормально: Telegram копит сообщения, бот заберёт их после
старта) и поднимет `postgres`. Вторая — обратный прокси.

Проверить, что `api` стартовал чисто (есть `Application startup complete`,
нет `Traceback`/`TokenValidationError`), и что он отвечает напрямую:

```bash
docker compose logs api --tail 50
curl -s localhost:8000/api/v1/status_DB
```

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

### 2.7. Проверить Telegram

Написать клиентскому Telegram-боту — должен ответить как раньше. Если молчит:

```bash
docker compose logs api | grep -iE "telegram|aiogram" | tail -20
```

`Conflict: terminated by other getUpdates request` означает, что с тем же
токеном где-то запущен второй экземпляр бота (например, локально) — его
нужно остановить.

---

## Откат

Если после деплоя что-то не работает и разбираться некогда:

```bash
docker compose --profile prod stop caddy
git checkout "$(cat .branch.backup)"
cp .env.backup .env
docker compose up -d --build
```

Товары и прочие данные основной базы не затрагиваются (`pgdata/` остаётся
на месте). Переписка консоли лежит в отдельной базе `gq_chat` и старой
версией просто не используется. Крайний случай — восстановление из
`backup-<дата>.sql`.

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
  сервере база видна из интернета. `ufw deny` здесь **не поможет**: Docker
  пишет свои правила iptables в обход `ufw`. Надёжно — поменять в
  `docker-compose.yaml` на `"127.0.0.1:54321:5432"` (доступ останется
  с самого сервера и через SSH-туннель).
- Пароли, которые выведет `seed_managers.py`, — временные. В интерфейсе
  консоли смены пароля нет; задать свой пароль менеджеру можно на сервере:
  `docker compose exec api python scripts/seed_managers.py --code <code> --password '<пароль>'`
  (коды — `director`, `kalbaeva`, `zhenibek`, `ivanova`, `mukhanov` из
  `src/settings/config.py`). Повторный запуск без `--password` пароли
  существующих менеджеров не меняет.
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
