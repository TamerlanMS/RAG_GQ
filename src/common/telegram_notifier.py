from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx
from src.common.logger import logger

if TYPE_CHECKING:
    from aiogram.types import Message

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_message_async(text: str, chat_id: str | None = None) -> bool:
    """Async send text message to Telegram group (HTML parse mode)."""
    token = TELEGRAM_BOT_TOKEN
    target = chat_id or TELEGRAM_CHAT_ID
    if not token or not target:
        logger.error("Telegram credentials missing: token=%s chat=%s", bool(token), bool(target))
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                TELEGRAM_API_URL.format(token=token),
                json={"chat_id": target, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error("send_message_async error: %s", e, exc_info=True)
        return False


async def send_file_to_group(
    message: "Message",
    media_type: str,
    username: str,
    caption: str = "",
) -> bool:
    """
    Download file via input-bot, re-upload to manager group via notification-bot.

    Why this approach:
      - input-bot  (TELEGRAM_INPUT_BOT_TOKEN) receives files from clients
      - notif-bot  (TELEGRAM_BOT_TOKEN)       is a member of the manager group
      - forward_message fails if input-bot is not in the group
      - Solution: download bytes via input-bot, upload via notif-bot
    """
    notif_token = TELEGRAM_BOT_TOKEN
    target = TELEGRAM_CHAT_ID
    input_token = os.getenv("TELEGRAM_INPUT_BOT_TOKEN", "")

    if not notif_token or not target or not input_token:
        logger.error(
            "send_file_to_group: missing env vars token=%s chat=%s input=%s",
            bool(notif_token), bool(target), bool(input_token),
        )
        return False

    if message.photo:
        file_id = message.photo[-1].file_id
        method, field, fname = "sendPhoto", "photo", "photo.jpg"
    elif message.document:
        file_id = message.document.file_id
        method, field, fname = "sendDocument", "document", (message.document.file_name or "file")
    elif message.video:
        file_id = message.video.file_id
        method, field, fname = "sendVideo", "video", (message.video.file_name or "video.mp4")
    elif message.audio:
        file_id = message.audio.file_id
        method, field, fname = "sendAudio", "audio", (message.audio.file_name or "audio.mp3")
    elif message.voice:
        file_id = message.voice.file_id
        method, field, fname = "sendVoice", "voice", "voice.ogg"
    else:
        logger.warning("send_file_to_group: unknown media type")
        return False

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Step 1: get file path via input-bot
            r = await client.get(
                f"https://api.telegram.org/bot{input_token}/getFile",
                params={"file_id": file_id},
            )
            r.raise_for_status()
            file_path = r.json()["result"]["file_path"]

            # Step 2: download file bytes
            r = await client.get(
                f"https://api.telegram.org/file/bot{input_token}/{file_path}"
            )
            r.raise_for_status()
            file_bytes = r.content

            # Step 3: upload via notification-bot with context caption
            cap = (
                f"<b>FILE FROM CLIENT</b>\n"
                f"Client: {username}\n"
                f"Type: {media_type}"
                + (f"\nNote: {caption}" if caption else "")
            )
            r = await client.post(
                f"https://api.telegram.org/bot{notif_token}/{method}",
                data={"chat_id": target, "caption": cap, "parse_mode": "HTML"},
                files={field: (fname, file_bytes)},
            )
            r.raise_for_status()
            logger.info("File(%s) from %s forwarded to manager group", media_type, username)
            return True

    except Exception as e:
        logger.error("send_file_to_group error: %s", e, exc_info=True)
        return False


async def send_bytes_to_group(
    file_bytes: bytes,
    file_name: str,
    media_type: str,
    caption: str = "",
    chat_id: str | None = None,
) -> bool:
    """
    Загрузить произвольные байты в группу менеджеров (для WhatsApp-файлов).

    media_type: image | document | video | audio | voice
    """
    token = TELEGRAM_BOT_TOKEN
    target = chat_id or TELEGRAM_CHAT_ID
    if not token or not target:
        logger.error("send_bytes_to_group: creds missing token=%s chat=%s", bool(token), bool(target))
        return False

    method, field = {
        "image":    ("sendPhoto",    "photo"),
        "document": ("sendDocument", "document"),
        "video":    ("sendVideo",    "video"),
        "audio":    ("sendAudio",    "audio"),
        "voice":    ("sendVoice",    "voice"),
    }.get(media_type, ("sendDocument", "document"))

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                data={"chat_id": target, "caption": caption[:1024], "parse_mode": "HTML"},
                files={field: (file_name, file_bytes)},
            )
            if resp.status_code != 200:
                logger.error("send_bytes_to_group %s failed: %s", method, resp.text[:300])
                # Фолбэк: фото могло не пройти по размеру/формату — шлём документом
                if method != "sendDocument":
                    resp = await client.post(
                        f"https://api.telegram.org/bot{token}/sendDocument",
                        data={"chat_id": target, "caption": caption[:1024], "parse_mode": "HTML"},
                        files={"document": (file_name, file_bytes)},
                    )
            resp.raise_for_status()
            logger.info("send_bytes_to_group OK: %s (%s, %d bytes)", file_name, media_type, len(file_bytes))
            return True
    except Exception as e:
        logger.error("send_bytes_to_group error: %s", e, exc_info=True)
        return False


def send_message_sync(text: str, chat_id: str | None = None) -> bool:
    """Sync send (works in ThreadPoolExecutor / LangGraph tools)."""
    token = TELEGRAM_BOT_TOKEN
    target = chat_id or TELEGRAM_CHAT_ID
    if not token or not target:
        logger.error("Telegram credentials missing: token=%s chat=%s", bool(token), bool(target))
        return False
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                TELEGRAM_API_URL.format(token=token),
                json={"chat_id": target, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error("send_message_sync error: %s", e, exc_info=True)
        return False
