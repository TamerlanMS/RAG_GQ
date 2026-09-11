"""
Персистентность переписки для менеджерской веб-консоли.

Модуль намеренно не зависит от FastAPI — им пользуются и WhatsApp-бот,
и роутер консоли.

Устройство: синхронное ядро (*_sync) + async-обёртки поверх asyncio.to_thread.
Ядро вызывается только из потока, потому что SQLAlchemy здесь синхронный,
а в event loop приложения уже живут aiogram-поллинг и вызовы OpenAI на 30-45 с.

Главный инвариант: ПЕРСИСТЕНТНОСТЬ НЕ ИМЕЕТ ПРАВА УРОНИТЬ БОТА.
Любая ошибка логируется и проглатывается — клиент всё равно получает ответ.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.common.logger import logger
from src.db.chat_database import ChatSessionLocal
from src.db.Models.chat_models import AUTHOR_SYSTEM, Chat, ChatMessage
from src.db.Models.manager_models import Manager

# Через сколько минут бездействия менеджера диалог автоматически возвращается боту.
# taken_over_at — не только момент перехвата: /reply (см. src/api/v1/console.py)
# обновляет его при каждом успешном ответе менеджера, так что здесь это
# фактически время последней активности менеджера в диалоге.
TAKEOVER_TIMEOUT_MINUTES: int = int(os.getenv("TAKEOVER_AUTO_RELEASE_MINUTES", "20"))

# Человекочитаемые подписи для превью в списке чатов, когда текста нет.
_TYPE_LABELS = {
    "image": "📷 Фото",
    "document": "📎 Документ",
    "video": "🎥 Видео",
    "audio": "🎵 Аудио",
    "voice": "🎤 Голосовое",
    "button": "🔘 Нажата кнопка",
    "system": "ℹ️ Системное",
}


def _preview(text_value: Optional[str], msg_type: str) -> str:
    if text_value and text_value.strip():
        return text_value.strip()[:300]
    return _TYPE_LABELS.get(msg_type, "Сообщение")


# ─── Синхронное ядро ─────────────────────────────────────────

def _upsert_chat(
    db: Any,
    channel: str,
    external_id: str,
    *,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
    phone: Optional[str] = None,
    tg_chat_id: Optional[int] = None,
) -> int:
    """
    Атомарный get-or-create чата.

    Не SELECT → if not: INSERT: два вебхука от одного номера могут прийти
    параллельно и словить IntegrityError. ON CONFLICT решает это за один round-trip
    и попутно освежает display_name.
    """
    stmt = pg_insert(Chat).values(
        channel=channel,
        external_id=external_id,
        display_name=display_name,
        username=username,
        phone=phone,
        tg_chat_id=tg_chat_id,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_chat_channel_external",
        set_={
            # COALESCE: не затираем известное имя пустым значением из следующего вебхука.
            "display_name": func.coalesce(stmt.excluded.display_name, Chat.display_name),
            "username": func.coalesce(stmt.excluded.username, Chat.username),
            "phone": func.coalesce(stmt.excluded.phone, Chat.phone),
            "tg_chat_id": func.coalesce(stmt.excluded.tg_chat_id, Chat.tg_chat_id),
            "updated_at": func.now(),
        },
    ).returning(Chat.id)
    return int(db.execute(stmt).scalar_one())


def save_message_sync(
    *,
    channel: str,
    external_id: str,
    direction: str,
    author: str,
    text_body: Optional[str] = None,
    msg_type: str = "text",
    author_manager_id: Optional[int] = None,
    file_name: Optional[str] = None,
    media_url: Optional[str] = None,
    external_msg_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    display_name: Optional[str] = None,
    username: Optional[str] = None,
    phone: Optional[str] = None,
    tg_chat_id: Optional[int] = None,
    bump_unread: bool = False,
) -> Optional[int]:
    """
    Сохраняет одно сообщение. Возвращает id или None
    (ошибка либо дубликат по external_msg_id).
    """
    db = ChatSessionLocal()
    try:
        chat_id = _upsert_chat(
            db,
            channel,
            external_id,
            display_name=display_name,
            username=username,
            phone=phone,
            tg_chat_id=tg_chat_id,
        )

        msg_stmt = pg_insert(ChatMessage).values(
            chat_id=chat_id,
            direction=direction,
            author=author,
            author_manager_id=author_manager_id,
            text=text_body,
            msg_type=msg_type,
            file_name=file_name,
            media_url=media_url,
            external_id=external_msg_id or None,
            extra=extra,
        )
        if external_msg_id:
            # Защита от переотправки вебхука Gupshup. index_where обязателен:
            # индекс частичный, без предиката Postgres его не выведет.
            msg_stmt = msg_stmt.on_conflict_do_nothing(
                index_elements=["chat_id", "external_id"],
                index_where=text("external_id IS NOT NULL"),
            )
        msg_stmt = msg_stmt.returning(ChatMessage.id)

        msg_id = db.execute(msg_stmt).scalar()
        if msg_id is None:
            # Дубликат — счётчики не трогаем.
            db.commit()
            logger.info("chat_store: пропущен дубликат сообщения %s", external_msg_id)
            return None

        # Счётчики — в той же транзакции, что и вставка.
        updates: Dict[str, Any] = {
            "last_message_at": func.now(),
            "last_message_preview": _preview(text_body, msg_type),
            "updated_at": func.now(),
        }
        if bump_unread and direction == "in":
            updates["unread_count"] = Chat.unread_count + 1

        db.query(Chat).filter(Chat.id == chat_id).update(updates, synchronize_session=False)
        db.commit()
        return int(msg_id)
    except Exception as e:
        db.rollback()
        logger.error("chat_store.save_message_sync failed: %s", e, exc_info=True)
        return None
    finally:
        db.close()


def is_taken_over_sync(channel: str, external_id: str) -> bool:
    """
    True, если диалог перехвачен менеджером и бот должен молчать.

    ПРИ ЛЮБОЙ ОШИБКЕ ВОЗВРАЩАЕТ False (fail-open): падение БД не должно
    заставить бота замолчать сразу для всех клиентов.
    """
    db = ChatSessionLocal()
    try:
        result = db.execute(
            select(Chat.is_taken_over).where(
                Chat.channel == channel, Chat.external_id == external_id
            )
        ).scalar()
        return bool(result)
    except Exception as e:
        logger.error("chat_store.is_taken_over_sync failed: %s", e, exc_info=True)
        return False
    finally:
        db.close()


def release_stale_takeovers_sync() -> int:
    """
    Возвращает боту диалоги, которые менеджер держит дольше
    TAKEOVER_TIMEOUT_MINUTES без единого ответа клиенту.

    Вызывается периодически из фонового цикла в src/main.py (lifespan),
    поэтому ошибка здесь не должна ронять приложение — только логируется.
    """
    db = ChatSessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=TAKEOVER_TIMEOUT_MINUTES)
        stale = db.execute(
            select(Chat).where(Chat.is_taken_over.is_(True), Chat.taken_over_at < cutoff)
        ).scalars().all()

        released = 0
        for chat in stale:
            manager = db.get(Manager, chat.taken_over_by_id) if chat.taken_over_by_id else None
            manager_label = manager.name if manager else "Менеджер"
            db.add(
                ChatMessage(
                    chat_id=chat.id,
                    direction="out",
                    author=AUTHOR_SYSTEM,
                    text=(
                        f"{manager_label} не отвечал клиенту {TAKEOVER_TIMEOUT_MINUTES} мин. — "
                        f"диалог автоматически возвращён боту"
                    ),
                    msg_type="system",
                )
            )
            chat.is_taken_over = False
            chat.taken_over_by_id = None
            chat.taken_over_at = None
            chat.updated_at = func.now()
            released += 1

        if released:
            db.commit()
            logger.info(
                "Автовозврат боту: %d диалог(ов) — менеджер не отвечал %d мин.",
                released, TAKEOVER_TIMEOUT_MINUTES,
            )
        return released
    except Exception as e:
        db.rollback()
        logger.error("release_stale_takeovers_sync failed: %s", e, exc_info=True)
        return 0
    finally:
        db.close()


# ─── Async-обёртки ───────────────────────────────────────────

async def save_message(**kwargs: Any) -> Optional[int]:
    try:
        return await asyncio.to_thread(save_message_sync, **kwargs)
    except Exception as e:
        logger.error("chat_store.save_message failed: %s", e, exc_info=True)
        return None


async def is_taken_over(channel: str, external_id: str) -> bool:
    try:
        return await asyncio.to_thread(is_taken_over_sync, channel, external_id)
    except Exception as e:
        logger.error("chat_store.is_taken_over failed: %s", e, exc_info=True)
        return False


async def release_stale_takeovers() -> int:
    try:
        return await asyncio.to_thread(release_stale_takeovers_sync)
    except Exception as e:
        logger.error("chat_store.release_stale_takeovers failed: %s", e, exc_info=True)
        return 0


# ─── Отправка клиенту (используется роутером консоли) ────────

async def send_to_client(
    channel: str,
    external_id: str,
    text_body: str,
    *,
    manager_id: Optional[int] = None,
) -> Optional[int]:
    """
    Отправляет сообщение клиенту в его канал и сохраняет его как сообщение менеджера.

    Возвращает id записанного сообщения или None, если доставка не удалась:
    запись делает сам транспортный хелпер и только в success-ветке, поэтому
    консоль не покажет доставленным то, что не доставлено.
    """
    if channel == "whatsapp":
        # Ленивый импорт: whatsapp.py импортирует этот модуль на уровне модуля.
        from src.whatsapp_bot import whatsapp as wa

        return await wa._send_whatsapp(
            external_id,
            text_body,
            persist_author="manager",
            persist_manager_id=manager_id,
        )

    raise ValueError(f"Канал '{channel}' не поддерживается для отправки из консоли")
