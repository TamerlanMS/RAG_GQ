"""
WhatsApp-бот через Gupshup (Мета-формат v3).

Webhook принимает входящие сообщения от Gupshup,
прогоняет через тот же GPT-4o + system_prompt что и Telegram-бот,
отвечает через Gupshup Send API.

Env:
  GUPSHUP_API_KEY        — API-ключ из Gupshup → Settings → API Keys
  GUPSHUP_APP_NAME       — Имя приложения (поле src.name при отправке)
  GUPSHUP_SOURCE_PHONE   — Номер телефона бота без + (напр. 77000000000)
  GUPSHUP_VERIFY_TOKEN   — Любой токен, который вы введёте в Gupshup
                           при настройке webhook (для верификации)
"""
from __future__ import annotations

import asyncio
import base64
import os
import random
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, Response
from src.common.logger import logger
from src.common.telegram_notifier import send_message_async

# ─── Настройки ───────────────────────────────────────────────
def _env(name: str, default: str = "") -> str:
    """os.getenv + срезание пробелов и \\r (защита от .env в формате CRLF)."""
    return (os.getenv(name) or default).strip().strip("\r\n")


GUPSHUP_API_KEY: str    = _env("GUPSHUP_API_KEY")
GUPSHUP_APP_NAME: str   = _env("GUPSHUP_APP_NAME", "GQGroup")
GUPSHUP_SOURCE_PHONE: str = _env("GUPSHUP_SOURCE_PHONE")
GUPSHUP_VERIFY_TOKEN: str = _env("GUPSHUP_VERIFY_TOKEN", "gqgroup_verify")

if not GUPSHUP_API_KEY:
    logger.warning("GUPSHUP_API_KEY пуст — исходящие сообщения WhatsApp отправляться не будут")
if not GUPSHUP_SOURCE_PHONE:
    logger.warning("GUPSHUP_SOURCE_PHONE пуст — исходящие сообщения WhatsApp отправляться не будут")

OPENAI_API_KEY: str = _env("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

GUPSHUP_SEND_URL = "https://api.gupshup.io/wa/api/v1/msg"
GUPSHUP_MEDIA_URL = "https://api.gupshup.io/wa/api/v1/msg/mediaUrl"

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "settings" / "system_prompt.txt"
SYSTEM_PROMPT: str = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""

# ─── История диалога (per WhatsApp user) ─────────────────────
MAX_HISTORY_PAIRS = 10
_wa_history: dict[str, list[dict]] = {}  # key = phone number string


def _get_history(phone: str) -> list[dict]:
    return _wa_history.get(phone, [])


def _add_to_history(phone: str, user_msg: str, assistant_msg: str) -> None:
    history = _wa_history.setdefault(phone, [])
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": assistant_msg})
    max_items = MAX_HISTORY_PAIRS * 2
    if len(history) > max_items:
        _wa_history[phone] = history[-max_items:]


# ─── Триггеры и эскалация (те же что в telegram bot) ─────────
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

_ESCALATION_PHRASES = (
    "передаю запрос",
    "передаю вас",
    "свяжется с вами",
    "свяжётся с вами",
    "уточнит наличие",
    "уточнит цену",
)


def _has_trigger(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _TRIGGER_KEYWORDS)


def _answer_escalates(answer: str) -> bool:
    a = answer.lower()
    return any(p in a for p in _ESCALATION_PHRASES)


# ─── GPT helpers ─────────────────────────────────────────────

async def _gpt_text(prompt: str, phone: str) -> str:
    from openai import AsyncOpenAI
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_get_history(phone))
    messages.append({"role": "user", "content": prompt})
    logger.info("_gpt_text calling OpenAI for phone=%s prompt_len=%d", phone, len(prompt))
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=600,
        temperature=0.3,
    )
    answer = response.choices[0].message.content.strip()
    logger.info("_gpt_text got answer len=%d for phone=%s", len(answer), phone)
    return answer


async def _gpt_vision(image_bytes: bytes, caption: str = "") -> str:
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


async def _download_media(media_id: str) -> bytes | None:
    """Скачивает медиафайл через Gupshup Media API."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # Сначала получаем URL файла
            r = await client.get(
                f"{GUPSHUP_MEDIA_URL}/{media_id}",
                headers={"apikey": GUPSHUP_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
            media_url = data.get("message", {}).get("url") or data.get("url")
            if not media_url:
                logger.error("No media URL in Gupshup response: %s", data)
                return None
            # Скачиваем сам файл
            r2 = await client.get(media_url)
            r2.raise_for_status()
            return r2.content
    except Exception as e:
        logger.error("_download_media error: %s", e)
        return None


# ─── Gupshup Send API ────────────────────────────────────────

async def _send_whatsapp(to_phone: str, text: str) -> None:
    """Отправить текстовое сообщение клиенту через Gupshup."""
    import json
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            payload = {
                "channel": "whatsapp",
                "source": GUPSHUP_SOURCE_PHONE,
                "destination": to_phone,
                "src.name": GUPSHUP_APP_NAME,
                "message": json.dumps({"type": "text", "text": text}),
            }
            logger.info("_send_whatsapp REQUEST to=%s source=%s app=%s", to_phone, GUPSHUP_SOURCE_PHONE, GUPSHUP_APP_NAME)
            resp = await client.post(
                GUPSHUP_SEND_URL,
                headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
                data=payload,
            )
            logger.info("_send_whatsapp RESPONSE status=%s body=%s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
    except Exception as e:
        logger.error("_send_whatsapp error (to=%s): %s", to_phone, e)


# ─── Обработка входящего сообщения ───────────────────────────

async def _process_message(
    phone: str,
    sender_name: str,
    msg_type: str,
    text_body: str,
    caption: str,
    media_id: str,
    file_name: str,
) -> None:
    """
    Вся бизнес-логика: GPT → ответ клиенту → уведомление менеджера.
    Вызывается как asyncio.create_task из webhook-хендлера.
    """
    logger.info("_process_message START phone=%s msg_type=%s text=%r", phone, msg_type, text_body[:50] if text_body else "")
    try:
        prompt_parts: list[str] = []
        vision_text = ""

        # Небольшая задержка чтобы имитировать набор текста (опционально)
        await asyncio.sleep(random.uniform(1.5, 3.0))
        logger.info("_process_message after sleep, building prompt")

        if msg_type == "text" and text_body:
            prompt_parts.append(f"Клиент написал: {text_body}")

        elif msg_type == "image" and media_id:
            image_bytes = await _download_media(media_id)
            if image_bytes:
                try:
                    vision_text = await _gpt_vision(image_bytes, caption)
                    prompt_parts.append(
                        f"Клиент прислал фото{f' с подписью «{caption}»' if caption else ''}. "
                        f"Vision определил: {vision_text}"
                    )
                except Exception as e:
                    logger.error("Vision error: %s", e)
                    prompt_parts.append(
                        f"Клиент прислал фото{f' с подписью «{caption}»' if caption else ''}, "
                        f"определить товар не удалось."
                    )
            else:
                prompt_parts.append("Клиент прислал фото, скачать не удалось.")

        elif msg_type in ("document", "video", "audio", "voice"):
            display = file_name or msg_type
            prompt_parts.append(f"Клиент прислал файл: {display}")
            answer = (
                "📎 Получил ваш файл — передаю менеджеру для обработки.\n\n"
                "Он свяжется с вами в течение рабочего дня."
            )
            await _send_whatsapp(phone, answer)
            await send_message_async(
                f"📎 <b>ФАЙЛ (WhatsApp)</b>\n"
                f"Клиент: {sender_name} ({phone})\n"
                f"Тип: {msg_type} | {display}"
                + (f"\nПодпись: {caption}" if caption else "")
            )
            _add_to_history(phone, f"Клиент прислал файл: {display}", answer)
            return

        else:
            prompt_parts.append("Клиент отправил сообщение без текста.")

        combined_prompt = "\n".join(prompt_parts)

        # GPT-ответ
        try:
            answer = await _gpt_text(combined_prompt, phone)
        except Exception as e:
            logger.error("GPT error for phone %s: %s", phone, e)
            answer = (
                "Чтобы предоставить точную информацию, подключаю профильного специалиста. "
                "Он свяжется с вами в ближайшее время."
            )

        # Отправляем ответ клиенту
        await _send_whatsapp(phone, answer)
        _add_to_history(phone, combined_prompt, answer)

        # Уведомления менеджеру
        escalated = _answer_escalates(answer)
        triggered = _has_trigger(text_body or caption)

        if msg_type == "image":
            await send_message_async(
                f"📸 <b>ФОТО (WhatsApp)</b>\n"
                f"Клиент: {sender_name} ({phone})"
                + (f"\nПодпись: {caption}" if caption else "")
                + (f"\nVision: {vision_text}" if vision_text else "\nVision: не определено")
            )

        if escalated:
            await send_message_async(
                f"🔔 <b>ЭСКАЛАЦИЯ (WhatsApp)</b>\n"
                f"Клиент: {sender_name} ({phone})\n"
                f"Сообщение клиента: {(text_body or caption)[:300]}\n"
                f"Принял бот: {answer[:400]}"
            )
        elif triggered and text_body:
            await send_message_async(
                f"💬 <b>ОБРАЩЕНИЕ (WhatsApp)</b>\n"
                f"Клиент: {sender_name} ({phone})\n"
                f"Сообщение: {text_body[:500]}"
            )

    except BaseException as e:
        logger.error("_process_message UNHANDLED ERROR phone=%s: %s (%s)", phone, e, type(e).__name__, exc_info=True)


# ─── FastAPI Router ───────────────────────────────────────────

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])


@router.get("/webhook")
async def verify_webhook(request: Request):
    """
    Верификация webhook.

    Два сценария:
      1) Meta Cloud API — GET с hub.mode/hub.verify_token/hub.challenge:
         возвращаем hub.challenge как plain text.
      2) Gupshup при сохранении Callback URL просто дёргает URL и ждёт HTTP 200
         без каких-либо параметров. Поэтому во всех остальных случаях
         отвечаем 200 OK, иначе Gupshup считает URL невалидным.
    """
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if challenge is not None:
        if mode == "subscribe" and token == GUPSHUP_VERIFY_TOKEN:
            logger.info("WhatsApp webhook verified (hub.challenge)")
            return Response(content=challenge, media_type="text/plain")
        logger.warning(
            "WhatsApp webhook verification failed: mode=%s token=%r (ожидался %r)",
            mode, token, GUPSHUP_VERIFY_TOKEN,
        )
        return Response(content="Forbidden", status_code=403)

    # Health-check от Gupshup / ручная проверка из браузера
    logger.info("WhatsApp webhook GET health-check, params=%s", params)
    return Response(content="OK", media_type="text/plain", status_code=200)


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Принимает события от Gupshup (Мета-формат v3).
    Немедленно возвращает 200, обрабатывает в фоне.
    """
    raw = await request.body()
    logger.info("Gupshup webhook IN: %s", raw.decode("utf-8", "replace")[:2000])

    try:
        body = await request.json()
    except Exception as e:
        logger.error("Gupshup webhook: невалидный JSON (%s)", e)
        return Response(content="OK", status_code=200)

    if not isinstance(body, dict):
        logger.warning("Gupshup webhook: неожиданный тип payload: %s", type(body))
        return Response(content="OK", status_code=200)

    # Meta v3 структура: body.entry[].changes[].value.messages[]
    entries = body.get("entry", [])
    if not entries:
        logger.warning(
            "Gupshup webhook: в payload нет entry[] — проверьте, что приложение "
            "настроено в формате Meta Cloud API v3. Ключи payload: %s",
            list(body.keys()),
        )

    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if change.get("field") != "messages":
                logger.info("Gupshup webhook: пропущен field=%s", change.get("field"))
                continue

            # Статусы доставки (sent/delivered/read) приходят в том же field
            if value.get("statuses") and not value.get("messages"):
                continue

            contacts = value.get("contacts", [{}])
            sender_name = contacts[0].get("profile", {}).get("name", "Клиент") if contacts else "Клиент"

            for msg in value.get("messages", []):
                phone    = msg.get("from", "")
                msg_type = msg.get("type", "text")
                text_body = msg.get("text", {}).get("body", "")
                caption   = ""
                media_id  = ""
                file_name = ""

                if msg_type == "image":
                    img = msg.get("image", {})
                    caption  = img.get("caption", "")
                    media_id = img.get("id", "")

                elif msg_type == "document":
                    doc = msg.get("document", {})
                    caption   = doc.get("caption", "")
                    media_id  = doc.get("id", "")
                    file_name = doc.get("filename", "файл")

                elif msg_type in ("video", "audio", "voice"):
                    media = msg.get(msg_type, {})
                    caption  = media.get("caption", "")
                    media_id = media.get("id", "")

                # Запускаем обработку в фоне — не блокируем Gupshup
                background_tasks.add_task(
                    _process_message,
                    phone=phone,
                    sender_name=sender_name,
                    msg_type=msg_type,
                    text_body=text_body,
                    caption=caption,
                    media_id=media_id,
                    file_name=file_name,
                )

    return Response(content="OK", status_code=200)
