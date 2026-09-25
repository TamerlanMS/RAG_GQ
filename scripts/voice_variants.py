"""
Отправляет одно и то же голосовое клиенту в нескольких форматах — чтобы
на iPhone выяснить, какой из них WhatsApp проигрывает.

Зачем: на iPhone WhatsApp строже к аудио, чем на компьютере, и на неподходящем
файле показывает «This audio is no longer available. Please ask … to re-send it»,
хотя на компьютере тот же файл играет. Проверить это можно только на самом
iPhone — скрипт шлёт варианты, клиент говорит, какие буквы играют.

Использование (на сервере):
    sudo docker compose exec -T api python scripts/voice_variants.py 77011234567

Номер — как в WhatsApp, без «+». Источник звука — последнее голосовое,
записанное менеджером в консоли (или путь внутри контейнера вторым аргументом).
Сообщения уходят НАСТОЯЩЕМУ клиенту — используйте свой тестовый номер.

Результат: если, например, играют только «A», в .env сервера задайте
VOICE_PROFILE=opus16 и перезапустите api.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

from src.common import media_store
from src.db.chat_database import ChatSessionLocal
from src.whatsapp_bot import whatsapp as wa

VARIANTS = [
    ("A", "opus16", "voice", "Opus 16 кГц — как голосовые самого WhatsApp"),
    ("B", "opus48", "voice", "Opus 48 кГц 48 кбит/с — сейчас по умолчанию"),
    ("C", "mp3", "audio", "MP3 — придёт аудиофайлом, не голосовым"),
    ("D", "aac", "audio", "AAC (m4a) — придёт аудиофайлом, не голосовым"),
]


def latest_manager_voice() -> Path | None:
    s = ChatSessionLocal()
    try:
        rel = s.execute(text(
            "SELECT extra->>'media_path' FROM chat_messages "
            "WHERE msg_type='voice' AND author='manager' AND extra ? 'media_path' "
            "ORDER BY id DESC LIMIT 1"
        )).scalar()
    finally:
        s.close()
    return media_store.resolve_path(rel) if rel else None


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    phone = "".join(ch for ch in sys.argv[1] if ch.isdigit())
    source = Path(sys.argv[2]) if len(sys.argv) > 2 else latest_manager_voice()
    if not source or not source.is_file():
        print("Нет исходной записи: запишите голосовое в консоли или передайте путь вторым аргументом")
        return 1

    base = media_store.public_base_url()
    if not base and not wa.WHATSAPP_DRY_RUN:
        print("Не задан DOMAIN / PUBLIC_BASE_URL в .env — WhatsApp не сможет забрать файл")
        return 1

    print(f"Источник: {source}\nКлиент: {phone}\n")
    raw = source.read_bytes()
    await wa._send_whatsapp(phone, "Тест голосовых: ниже 4 варианта A–D. "
                                   "Напишите, какие буквы проигрываются на iPhone.",
                            persist_author="manager")
    for letter, profile, kind, title in VARIANTS:
        ext, mime, _ = media_store.VOICE_PROFILES[profile]
        data = await asyncio.to_thread(media_store.encode_voice, raw, profile)
        if not data:
            print(f"{letter}: не удалось перекодировать")
            continue
        media = await asyncio.to_thread(media_store.save_bytes, data, kind, f"voice-{letter}{ext}", mime)
        if not media:
            print(f"{letter}: не удалось сохранить")
            continue
        await wa._send_whatsapp(phone, f"{letter}: {title}", persist_author="manager")
        url = (base or "") + media_store.signed_path_url(media["media_path"])
        msg_id = await wa._send_whatsapp_media(
            phone, "audio", url, media=media, file_name=f"voice-{letter}{ext}",
            persist_type=("voice" if kind == "voice" else "audio"),
        )
        print(f"{letter}: {title} — {len(data) // 1024} КБ — "
              f"{'отправлено' if msg_id else 'ОШИБКА отправки, см. логи'}")
        await asyncio.sleep(2)  # чтобы варианты пришли по порядку
    print("\nПопросите клиента открыть каждое на iPhone и сказать, какие буквы играют.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
