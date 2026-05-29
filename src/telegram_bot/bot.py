"""
Telegram-бот для общения с ИИ-агентом.

Пользователь пишет боту → бот вызывает /api/v1/ask → отвечает пользователю.
thread_id = @username (если есть) или tg_{user_id}.

Переменные окружения:
  TELEGRAM_INPUT_BOT_TOKEN — токен этого бота (отдельный от notification-бота)
  INTERNAL_API_URL         — базовый URL FastAPI (по умолчанию http://localhost:8000)
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx

from src.common.logger import logger

try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import CommandStart, Command
    from aiogram.types import Message
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties
    AIOGRAM_AVAILABLE = True
except ImportError:
    logger.warning("aiogram not installed — Telegram input bot disabled. Run: pip install aiogram")
    AIOGRAM_AVAILABLE = False

INPUT_BOT_TOKEN: str = os.getenv("TELEGRAM_INPUT_BOT_TOKEN", "")
INTERNAL_API_URL: str = os.getenv("INTERNAL_API_URL", "http://localhost:8000")
ASK_ENDPOINT = f"{INTERNAL_API_URL}/api/v1/ask"

bot: Optional[object] = None
dp = None

if AIOGRAM_AVAILABLE:
    dp = Dispatcher()

    def _get_thread_id(message: Message) -> str:
        username = message.from_user.username if message.from_user else None
        if username:
            return f"@{username}"
        return f"tg_{message.from_user.id}"

    async def _call_agent(user_input: str, thread_id: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                ASK_ENDPOINT,
                json={"user_input": user_input, "thread_id": thread_id},
            )
            resp.raise_for_status()
            return resp.json().get("answer", "Нет ответа")

    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        thread_id = _get_thread_id(message)
        logger.info("New user: thread_id=%s", thread_id)
        await message.answer(
            "Здравствуйте! Я — ИИ-менеджер компании <b>GQ-System Kazakhstan</b>.\n"
            "Помогу подобрать товар, уточнить цену и оформить заявку.\n\n"
            "Просто напишите что вас интересует 👇",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            "💡 <b>Что я умею:</b>\n"
            "• Найти товар по названию или описанию\n"
            "• Назвать актуальную цену и наличие\n"
            "• Оформить заявку и передать менеджеру\n"
            "• Ответить на вопросы о доставке и оплате\n\n"
            "Просто напишите ваш вопрос в свободной форме.",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(Command("reset"))
    async def cmd_reset(message: Message) -> None:
        thread_id = _get_thread_id(message)
        logger.info("Reset dialog for thread_id=%s", thread_id)
        await message.answer("🔄 История диалога сброшена. Начинаем с чистого листа!\nНапишите ваш вопрос.")

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        thread_id = _get_thread_id(message)
        user_text = message.text or ""
        logger.info("Message from thread_id=%s: %.80s", thread_id, user_text)
        await message.bot.send_chat_action(message.chat.id, "typing")
        try:
            answer = await _call_agent(user_text, thread_id)
        except httpx.HTTPStatusError as e:
            logger.error("API error %s for thread_id=%s", e.response.status_code, thread_id)
            answer = "Произошла ошибка при обращении к системе. Попробуйте чуть позже."
        except httpx.TimeoutException:
            logger.warning("API timeout for thread_id=%s", thread_id)
            answer = "Агент думает слишком долго. Попробуйте ещё раз."
        except Exception as e:
            logger.error("Unexpected error for thread_id=%s: %s", thread_id, e, exc_info=True)
            answer = "Непредвиденная ошибка. Попробуйте позже."
        await message.answer(answer)

    @dp.message(F.photo | F.document | F.video | F.audio | F.voice)
    async def handle_media(message: Message) -> None:
        thread_id = _get_thread_id(message)
        caption = message.caption or "без описания"
        logger.info("Media from thread_id=%s, caption=%.80s", thread_id, caption)
        await _call_agent(f"[Пользователь прислал файл/медиа. Описание: {caption}]", thread_id)
        await message.answer("Получил ваш файл — передаю менеджеру для обработки.\nОн свяжется с вами в течение рабочего дня.")


# ─── Запуск / остановка ─────────────────────────────────────

async def start_bot() -> None:
    global bot

    if not AIOGRAM_AVAILABLE:
        logger.warning("aiogram not installed — skipping Telegram input bot startup.")
        return

    if not INPUT_BOT_TOKEN:
        logger.warning("TELEGRAM_INPUT_BOT_TOKEN not set — input Telegram bot will not start.")
        return

    bot = Bot(
        token=INPUT_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("Starting Telegram input bot (polling)...")
    asyncio.create_task(dp.start_polling(bot, allowed_updates=["message"]))


async def stop_bot() -> None:
    global bot
    if bot and AIOGRAM_AVAILABLE and dp:
        await dp.stop_polling()
        await bot.session.close()
        logger.info("Telegram input bot stopped.")
