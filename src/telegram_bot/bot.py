"""
Telegram-бот GQ-System Kazakhstan.

Логика:
  /start → главное меню (3 кнопки)
  Inline-keyboard навигация по разделам
  Все входящие сообщения — батчинг:
    - 10 секунд ожидания после последнего сообщения (debounce)
    - за это время показываем "печатает..."
    - все сообщения из буфера обрабатываются одним GPT-запросом
    - перед отправкой — имитация набора текста (human delay)
  Фото → GPT-4o Vision → определяем товар → ответ + пересылка менеджеру
  Файлы → принимаем → пересылаем менеджеру

Env:
  TELEGRAM_INPUT_BOT_TOKEN  — токен этого бота
  TELEGRAM_BOT_TOKEN        — токен notification-бота
  TELEGRAM_CHAT_ID          — chat_id группы менеджеров
  OPENAI_API_KEY            — для GPT-4o / Vision
"""
from __future__ import annotations

import asyncio
import base64
import os
import random
from pathlib import Path
from typing import Optional

import httpx
from src.common.logger import logger
from src.common.telegram_notifier import send_file_to_group, send_message_async

try:
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import CommandStart, Command
    from aiogram.types import (
        Message, CallbackQuery,
        InlineKeyboardMarkup, InlineKeyboardButton,
    )
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties
    AIOGRAM_AVAILABLE = True
except ImportError:
    logger.warning("aiogram not installed — Telegram input bot disabled.")
    AIOGRAM_AVAILABLE = False

INPUT_BOT_TOKEN: str = os.getenv("TELEGRAM_INPUT_BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "settings" / "system_prompt.txt"
SYSTEM_PROMPT: str = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

# Сколько секунд ждать после последнего сообщения перед ответом
DEBOUNCE_SECONDS = 5

# Сколько пар сообщений хранить в истории (user + assistant)
MAX_HISTORY_PAIRS = 10

# Ключевые слова — триггеры пересылки менеджеру (по тексту клиента)
_TRIGGER_KEYWORDS = (
    "цен", "стоимост", "почем", "сколько стоит",
    "наличи", "есть ли", "в наличии",
    "артикул", "маркиров",
    "заказ", "купить", "приобрест",
    "спецификаци", "проект", "заявк", "расчёт", "расчет",
    "кп", "коммерческ",
    "доставк", "привезёт", "привезет",
    "скидк", "рассрочк", "оплат",
    "менеджер", "специалист", "человек", "живой",
    "звонок", "перезвон", "позвонит",
    "аналог",
    "штук", "шт", "единиц", "позиц",
)

# Фразы эскалации в ответе бота — тоже триггер для уведомления менеджера
_ESCALATION_PHRASES = (
    "передаю запрос",
    "передаю вас",
    "свяжется с вами",
    "свяжётся с вами",
    "уточнит наличие",
    "уточнит цену",
)


def _answer_escalates(answer: str) -> bool:
    a = answer.lower()
    return any(p in a for p in _ESCALATION_PHRASES)

# ─── Состояние батчинга (per user) ───────────────────────────
_pending_tasks: dict[int, asyncio.Task] = {}
_message_buffers: dict[int, list[Message]] = {}

# Локи: гарантируют, что второй батч не начнёт GPT-вызов
# раньше, чем первый запишет историю.
_user_locks: dict[int, asyncio.Lock] = {}

def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

# ─── История диалога (per user) ──────────────────────────────
# Формат: {user_id: [{"role": "user"|"assistant", "content": "..."}]}
_conversation_history: dict[int, list[dict]] = {}


def _get_history(user_id: int) -> list[dict]:
    return _conversation_history.get(user_id, [])


def _add_to_history(user_id: int, user_msg: str, assistant_msg: str) -> None:
    history = _conversation_history.setdefault(user_id, [])
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    # Обрезаем до MAX_HISTORY_PAIRS пар
    max_items = MAX_HISTORY_PAIRS * 2
    if len(history) > max_items:
        _conversation_history[user_id] = history[-max_items:]


def _clear_history(user_id: int) -> None:
    _conversation_history.pop(user_id, None)

# ─── Клавиатуры ──────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Получить КП по электрике",           callback_data="menu_electro")],
        [InlineKeyboardButton(text="🎥 Получить КП по слаботочным системам", callback_data="menu_weak")],
        [InlineKeyboardButton(text="👨‍💼 Связаться с менеджером",             callback_data="menu_manager")],
    ])

def kb_electro() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Прикрепить спецификацию / проект / заявку", callback_data="act_spec_electro")],
        [InlineKeyboardButton(text="💰 Запросить стоимость товара",                callback_data="act_price_electro")],
        [InlineKeyboardButton(text="⬅️ Назад",                                    callback_data="menu_back")],
    ])

def kb_weak() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Прикрепить спецификацию / проект / заявку", callback_data="act_spec_weak")],
        [InlineKeyboardButton(text="💰 Запросить стоимость товара",                callback_data="act_price_weak")],
        [InlineKeyboardButton(text="⬅️ Назад",                                    callback_data="menu_back")],
    ])

def kb_manager() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Заказать звонок",    callback_data="act_call")],
        [InlineKeyboardButton(text="💬 Написать менеджеру", callback_data="act_write")],
        [InlineKeyboardButton(text="📍 Адрес и контакты",   callback_data="act_contacts")],
        [InlineKeyboardButton(text="⬅️ Назад",              callback_data="menu_back")],
    ])

# ─── Helpers ─────────────────────────────────────────────────

def _username(message: Message) -> str:
    u = message.from_user
    if not u:
        return "Неизвестный"
    return f"@{u.username}" if u.username else f"tg_{u.id}"

def _user_display(message: Message) -> str:
    u = message.from_user
    if not u:
        return "Клиент"
    parts = [u.first_name or "", u.last_name or ""]
    name = " ".join(p for p in parts if p).strip() or "Клиент"
    return f"{name} ({_username(message)})"


def _has_trigger(texts: list[str]) -> bool:
    """Проверяет, содержит ли текст триггер для уведомления менеджера."""
    combined = " ".join(texts).lower()
    return any(kw in combined for kw in _TRIGGER_KEYWORDS)


async def _send_typing_loop(bot: Bot, chat_id: int, duration: float) -> None:
    """Отправляет 'печатает...' каждые 4 секунды в течение duration секунд."""
    elapsed = 0.0
    while elapsed < duration:
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        chunk = min(4.0, duration - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk


async def _gpt_text(combined_prompt: str, user_id: int) -> str:
    """Вызов GPT-4o с историей диалога, без инструментов."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_get_history(user_id))
    messages.append({"role": "user", "content": combined_prompt})
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-4o", "messages": messages, "max_tokens": 600, "temperature": 0.3},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def _gpt_vision(image_bytes: bytes, caption: str = "") -> str:
    """Анализ фото через GPT-4o Vision."""
    b64 = base64.b64encode(image_bytes).decode()
    prompt = (
        "Ты — эксперт по электротехническому оборудованию. "
        "Посмотри на фото и кратко (1–3 предложения) определи: "
        "что это за изделие, его тип, возможные характеристики или маркировку. "
        "Если не можешь определить — так и скажи честно."
    )
    if caption:
        prompt += f" Клиент написал: «{caption}»."

    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
    ]}]
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": "gpt-4o", "messages": messages, "max_tokens": 300, "temperature": 0.2},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def _download_photo(file_id: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{INPUT_BOT_TOKEN}/getFile",
                params={"file_id": file_id},
            )
            r.raise_for_status()
            file_path = r.json()["result"]["file_path"]
            r2 = await client.get(
                f"https://api.telegram.org/file/bot{INPUT_BOT_TOKEN}/{file_path}"
            )
            r2.raise_for_status()
            return r2.content
    except Exception as e:
        logger.error("_download_photo error: %s", e)
        return None


# ─── Батчинг и обработка ─────────────────────────────────────

async def _schedule_response(message: Message) -> None:
    """Добавить сообщение в буфер и запустить (или перезапустить) отложенную обработку."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Буферизуем сообщение
    _message_buffers.setdefault(user_id, []).append(message)

    # Отменяем предыдущий таймер — пришло новое сообщение
    existing = _pending_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()

    # Новый таймер на DEBOUNCE_SECONDS
    task = asyncio.create_task(
        _delayed_process(message.bot, chat_id, user_id)
    )
    _pending_tasks[user_id] = task


async def _delayed_process(bot: Bot, chat_id: int, user_id: int) -> None:
    """Ждём DEBOUNCE_SECONDS, затем обрабатываем все сообщения из буфера."""

    # Фаза 1: ждём, показываем "печатает..."
    try:
        await _send_typing_loop(bot, chat_id, DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return  # Пришло новое сообщение — перезапустят нас снова

    # Фазы 2–8 под lock — гарантируем что следующий батч
    # не читает историю раньше, чем предыдущий её запишет.
    async with _get_lock(user_id):

        # Фаза 2: забираем буфер
        messages = _message_buffers.pop(user_id, [])
        _pending_tasks.pop(user_id, None)
        if not messages:
            return

        username = _username(messages[0])
        user_display = _user_display(messages[0])

        # Разбиваем на типы
        texts: list[str] = []
        photos: list[Message] = []
        files: list[Message] = []

        for msg in messages:
            if msg.text:
                texts.append(msg.text)
            elif msg.photo:
                photos.append(msg)
            elif msg.document or msg.video or msg.audio or msg.voice:
                files.append(msg)

        # Фаза 3: Vision для фотографий
        vision_results: list[tuple[Message, str]] = []
        for msg in photos:
            photo_bytes = await _download_photo(msg.photo[-1].file_id)
            if photo_bytes:
                try:
                    result = await _gpt_vision(photo_bytes, msg.caption or "")
                    vision_results.append((msg, result))
                except Exception as e:
                    logger.error("Vision error: %s", e)
                    vision_results.append((msg, ""))
            else:
                vision_results.append((msg, ""))

        # Фаза 4: Формируем объединённый prompt
        prompt_parts: list[str] = []

        if texts:
            prompt_parts.append(f"Клиент написал: {' / '.join(texts)}")

        for msg, vision_text in vision_results:
            caption = msg.caption or ""
            if vision_text:
                prompt_parts.append(
                    f"Клиент прислал фото{f' с подписью «{caption}»' if caption else ''}. "
                    f"Vision определил: {vision_text}"
                )
            else:
                prompt_parts.append(
                    f"Клиент прислал фото{f' с подписью «{caption}»' if caption else ''}, "
                    f"определить товар не удалось."
                )

        if files:
            names = []
            for msg in files:
                if msg.document:
                    names.append(msg.document.file_name or "файл")
                elif msg.video:
                    names.append("видео")
                elif msg.audio:
                    names.append("аудио")
                else:
                    names.append("голосовое")
            prompt_parts.append(f"Клиент прислал файл(ы): {', '.join(names)}")

        combined_prompt = "\n".join(prompt_parts) if prompt_parts else "Клиент написал сообщение без текста"

        # Фаза 5: GPT-ответ
        await bot.send_chat_action(chat_id, "typing")
        try:
            if files and not texts and not photos:
                answer = (
                    "📎 Получил ваш файл — передаю менеджеру для обработки.\n\n"
                    "Он свяжется с вами в течение рабочего дня."
                )
            else:
                answer = await _gpt_text(combined_prompt, user_id)
        except Exception as e:
            logger.error("GPT error for user %s: %s", user_id, e)
            answer = (
                "Чтобы предоставить точную информацию, подключаю профильного специалиста. "
                "Он свяжется с вами в ближайшее время."
            )

        # Фаза 6: Имитация набора текста
        typing_delay = min(len(answer) / 100, 4.0) + random.uniform(0.8, 2.0)
        await _send_typing_loop(bot, chat_id, typing_delay)

        # Фаза 7: Отправка + сохранение истории (внутри lock!)
        await bot.send_message(chat_id, answer)
        _add_to_history(user_id, combined_prompt, answer)

        # Фаза 8: Уведомления менеджеру
        text_triggered = _has_trigger(texts)
        escalated = _answer_escalates(answer)

        for msg, vision_text in vision_results:
            vision_note = f"\n📸 Vision: {vision_text}" if vision_text else "\n📸 Vision: не определено"
            await send_message_async(
                f"📸 <b>ФОТО ОТ КЛИЕНТА</b>\n"
                f"Клиент: {user_display}"
                + (f"\nПодпись: {msg.caption}" if msg.caption else "")
                + vision_note
            )
            await send_file_to_group(msg, "фото", username, msg.caption or "")

        for msg in files:
            if msg.document:
                media_type, fname = "документ", (msg.document.file_name or "файл")
            elif msg.video:
                media_type, fname = "видео", (msg.video.file_name or "video.mp4")
            elif msg.audio:
                media_type, fname = "аудио", (msg.audio.file_name or "audio")
            else:
                media_type, fname = "голосовое", "voice.ogg"
            await send_message_async(
                f"📎 <b>ФАЙЛ ОТ КЛИЕНТА</b>\n"
                f"Клиент: {user_display}\n"
                f"Тип: {media_type} | {fname}"
                + (f"\nПримечание: {msg.caption}" if msg.caption else "")
            )
            await send_file_to_group(msg, media_type, username, msg.caption or "")

        if texts:
            if escalated:
                # Эскалация — пересылаем с полным контекстом (что собрал бот)
                await send_message_async(
                    f"🔔 <b>ЭСКАЛАЦИЯ — передача специалисту</b>\n"
                    f"Клиент: {user_display}\n"
                    f"Сообщение клиента: {' / '.join(texts)[:300]}\n"
                    f"Принял бот: {answer[:400]}"
                )
            elif text_triggered:
                await send_message_async(
                    f"💬 <b>ОБРАЩЕНИЕ</b>\n"
                    f"Клиент: {user_display}\n"
                    f"Сообщение: {' / '.join(texts)[:500]}"
                )


# ─── Dispatcher ──────────────────────────────────────────────

bot_instance: Optional[object] = None
dp = None

if AIOGRAM_AVAILABLE:
    dp = Dispatcher()

    # ── /start — немедленный ответ без батчинга ───────────────
    @dp.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        _clear_history(message.from_user.id)
        await message.answer(
            "👋 Добро пожаловать в <b>GQ Group</b>! Меня зовут Диана, "
            "я менеджер по работе с клиентами.\n\n"
            "Спасибо за обращение. Выберите интересующий вас раздел:\n\n"
            "⚡ Получить КП по электрике\n"
            "🎥 Получить КП по слаботочным системам\n"
            "👨‍💼 Связаться с менеджером",
            reply_markup=kb_main(),
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            "Я помогу вам:\n"
            "• Получить КП по электрике или слаботочным системам\n"
            "• Связаться с менеджером\n"
            "• Ответить на вопросы о товарах, доставке и ценах\n\n"
            "Напишите что вас интересует или нажмите /start"
        )

    # ── Callback-кнопки — немедленные ────────────────────────
    @dp.callback_query(F.data == "menu_back")
    async def cb_back(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "👋 Добро пожаловать в <b>GQ Group</b>! Меня зовут Диана, "
            "я менеджер по работе с клиентами.\n\n"
            "Спасибо за обращение. Выберите интересующий вас раздел:",
            reply_markup=kb_main(),
        )
        await call.answer()

    @dp.callback_query(F.data == "menu_electro")
    async def cb_electro(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "⚡ <b>Получить КП по электрике</b>\n\nВыберите действие:",
            reply_markup=kb_electro(),
        )
        await call.answer()

    @dp.callback_query(F.data == "menu_weak")
    async def cb_weak(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "🎥 <b>Получить КП по слаботочным системам</b>\n\nВыберите действие:",
            reply_markup=kb_weak(),
        )
        await call.answer()

    @dp.callback_query(F.data == "menu_manager")
    async def cb_manager(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "👨‍💼 <b>Связаться с менеджером</b>\n\nВыберите действие:",
            reply_markup=kb_manager(),
        )
        await call.answer()

    @dp.callback_query(F.data.in_({"act_spec_electro", "act_spec_weak"}))
    async def cb_spec(call: CallbackQuery) -> None:
        section = "электрике" if call.data == "act_spec_electro" else "слаботочным системам"
        await call.message.edit_text(
            f"📎 Прикрепите файл в формате Excel, PDF, Word или архив.\n\n"
            f"После получения наши специалисты по <b>{section}</b> подготовят "
            f"коммерческое предложение и свяжутся с вами."
        )
        await call.answer()

    @dp.callback_query(F.data.in_({"act_price_electro", "act_price_weak"}))
    async def cb_price(call: CallbackQuery) -> None:
        section = "электротехническому оборудованию" if call.data == "act_price_electro" else "слаботочному оборудованию"
        await call.message.edit_text(
            f"💰 Напишите наименование товара, артикул или прикрепите список позиций.\n\n"
            f"Мы подготовим предложение по <b>{section}</b> в ближайшее время."
        )
        await call.answer()

    @dp.callback_query(F.data == "act_call")
    async def cb_call(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "📞 Напишите ваше имя и номер телефона.\n\n"
            "Менеджер свяжется с вами в ближайшее время."
        )
        await call.answer()

    @dp.callback_query(F.data == "act_write")
    async def cb_write(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "💬 Опишите ваш вопрос.\n\nМенеджер ответит вам в ближайшее время."
        )
        await call.answer()

    @dp.callback_query(F.data == "act_contacts")
    async def cb_contacts(call: CallbackQuery) -> None:
        await call.message.edit_text(
            "📍 <b>Наши адреса:</b>\n\n"
            "🏢 <b>Офис</b> (встречи, документы):\n"
            "ул. Момышулы 16, Астана\n"
            "Пн–Пт, 09:00–18:00\n\n"
            "🏭 <b>Склад</b> (самовывоз):\n"
            "Орлыкол 10/1, Астана\n"
            "Пн–Пт, 09:00–17:00\n\n"
            "📞 Телефон: +77777777777\n\n"
            "Вернуться в меню: /start"
        )
        await call.answer()

    # ── Входящие сообщения — всё через батчинг ───────────────

    @dp.message(F.photo)
    async def handle_photo(message: Message) -> None:
        await _schedule_response(message)

    @dp.message(F.document | F.video | F.audio | F.voice)
    async def handle_document(message: Message) -> None:
        await _schedule_response(message)

    @dp.message(F.text)
    async def handle_text(message: Message) -> None:
        await _schedule_response(message)


# ─── Запуск / остановка ──────────────────────────────────────

async def start_bot() -> None:
    global bot_instance

    if not AIOGRAM_AVAILABLE:
        logger.warning("aiogram not installed — skipping Telegram input bot startup.")
        return
    if not INPUT_BOT_TOKEN:
        logger.warning("TELEGRAM_INPUT_BOT_TOKEN not set — input Telegram bot will not start.")
        return

    bot_instance = Bot(
        token=INPUT_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    logger.info("Starting Telegram input bot (polling)...")
    asyncio.create_task(dp.start_polling(bot_instance, allowed_updates=["message", "callback_query"]))


async def stop_bot() -> None:
    global bot_instance
    if bot_instance and AIOGRAM_AVAILABLE and dp:
        await dp.stop_polling()
        await bot_instance.session.close()
        logger.info("Telegram input bot stopped.")
