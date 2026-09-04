"""
Отправка тестового входящего сообщения в веб-консоль — как будто написал клиент.

Реальный Gupshup для этого не нужен: скрипт шлёт на вебхук приложения payload
в том же формате Meta Cloud API v3, который приходит от Gupshup.

Использование:
    docker compose exec api python scripts/send_test_message.py "Здравствуйте, нужен кабель"
    docker compose exec api python scripts/send_test_message.py "Есть ли IEK?" --phone 77011234567
    docker compose exec api python scripts/send_test_message.py "Привет" --name "Асель Ким"

ВАЖНО: запускать через `docker compose exec`, а не напрямую в терминале Windows —
иначе кириллица уйдёт в неверной кодировке.

Чтобы бот отвечал, но НИЧЕГО не уходило реальным клиентам в WhatsApp,
держите WHATSAPP_DRY_RUN=true в .env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from urllib import error, request

DEFAULT_PHONE = "77011234567"
DEFAULT_NAME = "Тестовый клиент"


def main() -> int:
    parser = argparse.ArgumentParser(description="Отправить тестовое сообщение в консоль")
    parser.add_argument("text", help="Текст сообщения от клиента")
    parser.add_argument("--phone", default=DEFAULT_PHONE,
                        help=f"Номер клиента без «+» (по умолчанию {DEFAULT_PHONE})")
    parser.add_argument("--name", default=DEFAULT_NAME,
                        help="Имя клиента, как его показывает WhatsApp")
    parser.add_argument("--url", default=os.getenv("TEST_WEBHOOK_URL", "http://localhost:8000"),
                        help="Базовый URL приложения")
    args = parser.parse_args()

    payload = {
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "contacts": [{"profile": {"name": args.name}, "wa_id": args.phone}],
                    "messages": [{
                        "from": args.phone,
                        "id": "wamid.TEST-" + uuid.uuid4().hex[:12],
                        "type": "text",
                        "text": {"body": args.text},
                    }],
                },
            }],
        }],
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        args.url.rstrip("/") + "/api/v1/whatsapp/webhook",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            status = resp.status
    except error.URLError as e:
        print(f"ОШИБКА: не удалось достучаться до {args.url} — {e}", file=sys.stderr)
        print("Проверьте, что приложение запущено: docker compose ps", file=sys.stderr)
        return 1

    if status != 200:
        print(f"ОШИБКА: вебхук ответил {status}", file=sys.stderr)
        return 1

    print(f"Отправлено от {args.name} ({args.phone}): {args.text}")
    print("Через несколько секунд сообщение появится в консоли на /console")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
