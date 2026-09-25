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

# В python:3.10-slim нет /etc/mime.types, и mimetypes не знает .ogg, .m4a,
# .webp, .docx/.xlsx/.pptx, а .3gp считает аудио. Тип файла по расширению
# здесь критичен: WhatsApp проверяет Content-Type, с которым Gupshup скачивает
# файл по ссылке, и отвергает application/octet-stream
# («Unsupported Audio mime type application/octet-stream», код 131053).
_EXT_MIME = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".oga": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".amr": "audio/amr",
    ".mp4": "video/mp4",
    ".3gp": "video/3gpp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
for _ext, _mime in _EXT_MIME.items():
    mimetypes.add_type(_mime, _ext)


def mime_for_name(name: str) -> str:
    """MIME по расширению имени файла; application/octet-stream, если неизвестно."""
    ext = Path(name or "").suffix.lower()
    return _EXT_MIME.get(ext) or mimetypes.guess_type(name or "")[0] or "application/octet-stream"

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


# ─── Исходящие файлы (менеджер → клиент) ─────────────────────
# Gupshup не принимает файл в запросе — только ссылку, по которой он сам его
# скачает. Поэтому файл менеджера сначала сохраняется сюда же, а Gupshup
# получает короткоживущую подписанную ссылку на /console/media-out.
# Подпись — по пути файла, а не по id сообщения: сообщение записывается
# в БД только ПОСЛЕ успешной отправки, и id на момент отправки ещё нет.

_OUT_URL_TTL_SECONDS = 3600

# Что WhatsApp принимает как фото/видео/аудио; всё остальное уходит документом.
_OUT_IMAGE = frozenset({"image/jpeg", "image/png"})
_OUT_VIDEO = frozenset({"video/mp4", "video/3gpp"})
_OUT_AUDIO = frozenset({"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"})

# Лимиты WhatsApp Business на размер файла, байт.
OUT_LIMITS = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
}
OUT_MAX_BYTES = max(OUT_LIMITS.values())


def guess_mime(file_name: Optional[str], declared: Optional[str]) -> str:
    base = (declared or "").split(";")[0].strip().lower()
    if base and base != "application/octet-stream":
        return base
    return (mimetypes.guess_type(file_name or "")[0] or "application/octet-stream").lower()


def classify_outgoing(mime: str) -> str:
    """Тип сообщения WhatsApp для файла менеджера: image | video | audio | document."""
    if mime in _OUT_IMAGE:
        return "image"
    if mime in _OUT_VIDEO:
        return "video"
    if mime in _OUT_AUDIO:
        return "audio"
    return "document"


def public_base_url() -> Optional[str]:
    """Внешний адрес приложения — по нему Gupshup забирает файл."""
    explicit = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    domain = os.getenv("DOMAIN", "").strip()
    return f"https://{domain}" if domain else None


def _sign_path(rel: str, exp: int) -> str:
    return hmac.new(_SECRET, f"media-out:{rel}:{exp}".encode(), hashlib.sha256).hexdigest()


def signed_path_url(rel: str) -> str:
    """Относительная ссылка на файл по пути, действует час."""
    from urllib.parse import quote

    exp = int(time.time()) + _OUT_URL_TTL_SECONDS
    return f"/api/v1/console/media-out?p={quote(rel, safe='/')}&exp={exp}&sig={_sign_path(rel, exp)}"


def verify_path_signature(rel: str, exp: int, sig: str) -> bool:
    if not _SECRET or exp < int(time.time()):
        return False
    return hmac.compare_digest(_sign_path(rel, exp), sig)


def delete(rel: str) -> None:
    path = resolve_path(rel)
    if path is not None:
        try:
            path.unlink()
        except Exception as e:
            logger.warning("media_store.delete failed for %s: %s", rel, e)



# ─── Голосовые из консоли ────────────────────────────────────

VOICE_MAX_SECONDS = 15 * 60


def to_whatsapp_voice(data: bytes) -> Optional[bytes]:
    """
    Перекодирует запись из браузера в OGG/Opus моно — единственный формат,
    который WhatsApp показывает клиенту как голосовое (с волной), а не как
    аудиофайл. Вход — что угодно, что понимает ffmpeg (WebM из Chrome/Firefox,
    MP4/AAC из Safari). None — ffmpeg не справился (битый файл, не аудио).

    Через временные файлы, а не pipe: у MP4 из Safari индекс (moov) бывает
    в конце файла, и из несикаемого потока ffmpeg его не прочитает.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in"
        dst = Path(tmp) / "out.ogg"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(src),
                    "-vn", "-ac", "1", "-ar", "48000",
                    "-c:a", "libopus", "-b:a", "32k", "-application", "voip",
                    "-t", str(VOICE_MAX_SECONDS),
                    str(dst),
                ],
                capture_output=True,
                timeout=120,
            )
        except Exception as e:
            logger.error("media_store.to_whatsapp_voice: ffmpeg не запустился: %s", e)
            return None
        if proc.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
            logger.warning("media_store.to_whatsapp_voice: ffmpeg rc=%s: %s",
                           proc.returncode, proc.stderr.decode(errors="replace")[:300])
            return None
        return dst.read_bytes()
