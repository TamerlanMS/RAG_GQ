"""
Хранение вложений из WhatsApp (фото, видео, аудио, документы, стикеры) для веб-консоли.

Зачем скачивать, а не хранить ссылку Gupshup: ссылка из вебхука живёт недолго
и требует apikey — через день-два менеджер открыл бы пустой пузырь. Поэтому
файл скачивается сразу при получении и лежит на диске сервера.

Где лежит: MEDIA_DIR (по умолчанию /app/media — внутри bind-mount репозитория,
то есть на хосте это ./media рядом с pgdata/). В БД пишется только
относительный путь в chat_messages.extra["media_path"] — новые колонки не
нужны (create_all не делает ALTER TABLE).

Как отдаётся: не по JWT, а по подписанной ссылке с ограниченным сроком
(`?exp=...&sig=...`). Причина — <img>/<video>/<audio> в браузере не умеют
слать заголовок Authorization, а класть сам JWT в URL нельзя: он осядет в
логах nginx. Подпись — HMAC от id сообщения и срока на секрете API_TOKEN
(тот же секрет, что и у JWT консоли), выдаётся только вошедшему менеджеру
вместе со списком сообщений.
"""
from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.common.logger import logger

MEDIA_DIR: Path = Path(os.getenv("MEDIA_DIR", "/app/media"))

# Типы сообщений, у которых есть файл.
MEDIA_TYPES = frozenset({"image", "document", "video", "audio", "voice", "sticker"})

# Сколько живёт выданная ссылка. Округляется до часа, чтобы при поллинге
# ссылка на одно и то же сообщение не менялась и браузер брал файл из кеша.
_URL_TTL_SECONDS = 24 * 3600

_SECRET: bytes = os.getenv("API_TOKEN", "").encode()

# Расширение по умолчанию, если его не дали ни имя файла, ни MIME.
_DEFAULT_EXT = {
    "image": ".jpg",
    "sticker": ".webp",
    "video": ".mp4",
    "audio": ".ogg",
    "voice": ".ogg",
    "document": ".bin",
}

# mimetypes на некоторых системах отдаёт для этих типов экзотику (.jpe, .oga).
_PREFERRED_EXT = {
    "image/jpeg": ".jpg",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "image/webp": ".webp",
}


def _pick_extension(msg_type: str, file_name: Optional[str], mime: Optional[str]) -> str:
    if file_name:
        suffix = Path(file_name).suffix.lower()
        # Только «нормальные» расширения — имя присылает клиент.
        if 1 < len(suffix) <= 10 and suffix[1:].isalnum():
            return suffix
    if mime:
        base = mime.split(";")[0].strip().lower()
        ext = _PREFERRED_EXT.get(base) or mimetypes.guess_extension(base)
        if ext:
            return ext
    return _DEFAULT_EXT.get(msg_type, ".bin")


def save_bytes(
    data: bytes,
    msg_type: str,
    file_name: Optional[str] = None,
    mime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Пишет файл на диск. Возвращает поля для chat_messages.extra
    или None при ошибке (ошибка логируется — бот работает дальше).

    Имя на диске — случайное: имя от клиента в путь не попадает никогда
    (только его расширение, и то после проверки).
    """
    try:
        now = datetime.now(timezone.utc)
        rel = Path(f"{now:%Y}") / f"{now:%m}" / f"{uuid.uuid4().hex}{_pick_extension(msg_type, file_name, mime)}"
        target = MEDIA_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        guessed = mimetypes.guess_type(target.name)[0]
        return {
            "media_path": rel.as_posix(),
            "media_mime": (mime.split(";")[0].strip() if mime else None) or guessed or "application/octet-stream",
            "media_size": len(data),
        }
    except Exception as e:
        logger.error("media_store.save_bytes failed: %s", e, exc_info=True)
        return None


def resolve_path(rel: str) -> Optional[Path]:
    """Абсолютный путь к файлу или None, если он вне MEDIA_DIR / не существует."""
    try:
        base = MEDIA_DIR.resolve()
        full = (base / rel).resolve()
        if base not in full.parents or not full.is_file():
            return None
        return full
    except Exception:
        return None


def _sign(message_id: int, exp: int) -> str:
    return hmac.new(_SECRET, f"media:{message_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def signed_url(message_id: int) -> str:
    """Ссылка на файл сообщения для консоли, действует примерно сутки."""
    exp = (int(time.time()) // 3600 + 1) * 3600 + _URL_TTL_SECONDS
    return f"/api/v1/console/media/{message_id}?exp={exp}&sig={_sign(message_id, exp)}"


def verify_signature(message_id: int, exp: int, sig: str) -> bool:
    if not _SECRET or exp < int(time.time()):
        return False
    return hmac.compare_digest(_sign(message_id, exp), sig)
