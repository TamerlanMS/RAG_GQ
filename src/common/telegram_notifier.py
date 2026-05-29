"""
Модуль отправки сообщений в Telegram-группу через бота.

Переменные окружения:
  TELEGRAM_BOT_TOKEN  — токен бота (получить у @BotFather)
  TELEGRAM_CHAT_ID    — ID группы/канала (например, -1001234567890)
"""
from __future__ import annotations

import os
import httpx
from src.common.logger import logger

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_message_async(text: str, chat_id: str | None = None) -> bool:
    """
    Асинхронная отправка сообщения в Telegram.

    :param text: Текст сообщения (поддерживает HTML).
    :param chat_id: ID чата — если None, берётся из TELEGRAM_CHAT_ID.
    :return: True при успехе, False при ошибке.
    """
    token = TELEGRAM_BOT_TOKEN
    target = chat_id or TELEGRAM_CHAT_ID

    if not token or not target:
        logger.error(
            "Telegram credentials missing: TELEGRAM_BOT_TOKEN=%s, TELEGRAM_CHAT_ID=%s",
            bool(token),
            bool(target),
        )
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Telegram message sent to chat_id=%s", target)
            return True
    except httpx.HTTPStatusError as e:
        logger.error("Telegram API error: %s — %s", e.response.status_code, e.response.text)
        return False
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e, exc_info=True)
        return False


def send_message_sync(text: str, chat_id: str | None = None) -> bool:
    """
    Синхронная отправка через httpx.Client — работает в любом потоке,
    в том числе внутри ThreadPoolExecutor (LangGraph tools).
    """
    token = TELEGRAM_BOT_TOKEN
    target = chat_id or TELEGRAM_CHAT_ID

    if not token or not target:
        logger.error(
            "Telegram credentials missing: TELEGRAM_BOT_TOKEN=%s, TELEGRAM_CHAT_ID=%s",
            bool(token),
            bool(target),
        )
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Telegram message sent to chat_id=%s", target)
            return True
    except httpx.HTTPStatusError as e:
        logger.error("Telegram API error: %s — %s", e.response.status_code, e.response.text)
        return False
    except Exception as e:
        logger.error("send_message_sync error: %s", e, exc_info=True)
        return False
