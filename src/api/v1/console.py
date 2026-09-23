"""
API менеджерской веб-консоли.

Отдельный роутер, а не рост endpoints.py (там уже 352 строки и смешаны
агент, БД, товары и поставщики). Все роуты работают с базой переписки
через get_chat_db — основная база консоли не нужна.
"""
from __future__ import annotations

import asyncio
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from src.common import chat_store, media_store
from src.common.auth import (
    burn_dummy_hash,
    check_login_rate,
    create_access_token,
    get_current_manager,
    hash_password,
    register_failed_login,
    require_director,
    reset_login_attempts,
    verify_password,
)
from src.common.logger import logger
from src.common.phone import normalize_phone
from src.common.Schemas.console_schemas import (
    ActionResponse,
    ChatListResponse,
    ChatOut,
    LoginRequest,
    LoginResponse,
    ManagerOut,
    ManagerStatEntry,
    MessageListResponse,
    MessageOut,
    PasswordChangeRequest,
    ReplyRequest,
    StatsResponse,
    TakenOverBy,
    TakeoverRequest,
)
from src.db.chat_database import get_chat_db
from src.db.Models.chat_models import AUTHOR_MANAGER, AUTHOR_SYSTEM, CHANNEL_WHATSAPP, Chat, ChatMessage
from src.db.Models.manager_models import Manager

router: APIRouter = APIRouter(prefix="/console")

# Одинаковый ответ и при неизвестном номере, и при неверном пароле —
# чтобы нельзя было перебором выяснить, какие номера зарегистрированы.
_BAD_CREDENTIALS = "Неверный телефон или пароль"


@router.post("/login", response_model=LoginResponse, tags=["console"])
def login(body: LoginRequest, db: Session = Depends(get_chat_db)) -> LoginResponse:
    """Вход менеджера по телефону и паролю."""
    phone = normalize_phone(body.phone)
    if phone is None:
        # 401, а не 422: не подсказываем перебирающему, что формат номера неверен.
        burn_dummy_hash()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)

    check_login_rate(phone)

    manager = db.query(Manager).filter(Manager.phone == phone).one_or_none()
    if manager is None or not manager.is_active:
        burn_dummy_hash()
        register_failed_login(phone)
        logger.warning("Неудачная попытка входа в консоль: phone=%s (менеджер не найден)", phone)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)

    if not verify_password(body.password, manager.password_hash):
        register_failed_login(phone)
        logger.warning("Неудачная попытка входа в консоль: phone=%s (неверный пароль)", phone)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)

    reset_login_attempts(phone)
    token, expires_in = create_access_token(manager)
    logger.info("Вход в консоль: %s (%s)", manager.code, phone)
    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        manager=ManagerOut.model_validate(manager),
    )


@router.get("/me", response_model=ManagerOut, tags=["console"])
def me(manager: Manager = Depends(get_current_manager)) -> ManagerOut:
    """Профиль текущего менеджера. Фронтенд дёргает при старте для проверки токена."""
    return ManagerOut.model_validate(manager)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["console"],
)
def change_password(
    body: PasswordChangeRequest,
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> Response:
    """Смена собственного пароля."""
    if not verify_password(body.old_password, manager.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль указан неверно"
        )
    manager.password_hash = hash_password(body.new_password)
    db.commit()
    logger.info("Смена пароля в консоли: %s", manager.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────── Чаты ─────────────────────────── #

def _chat_out(chat: Chat, holder: Optional[Manager] = None) -> ChatOut:
    return ChatOut(
        id=chat.id,
        channel=chat.channel,
        external_id=chat.external_id,
        display_name=chat.display_name,
        phone=chat.phone,
        last_message_at=chat.last_message_at,
        last_message_preview=chat.last_message_preview,
        unread_count=chat.unread_count,
        is_taken_over=chat.is_taken_over,
        taken_over_by=(TakenOverBy(id=holder.id, name=holder.name) if holder else None),
    )


def _message_out(msg: ChatMessage, manager_name: Optional[str] = None) -> MessageOut:
    extra = msg.extra if isinstance(msg.extra, dict) else {}
    has_media = bool(extra.get("media_path"))
    return MessageOut(
        id=msg.id,
        direction=msg.direction,
        author=msg.author,
        author_manager_name=manager_name,
        text=msg.text,
        msg_type=msg.msg_type,
        file_name=msg.file_name,
        media_url=(media_store.signed_url(msg.id) if has_media else None),
        media_mime=(extra.get("media_mime") if has_media else None),
        media_size=(extra.get("media_size") if has_media else None),
        created_at=msg.created_at,
    )


def _get_chat_or_404(db: Session, chat_id: int) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Диалог не найден")
    return chat


@router.get("/chats", response_model=ChatListResponse, tags=["console"])
def list_chats(
    query: Optional[str] = None,
    channel: Optional[str] = None,
    taken_over: Optional[bool] = None,
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> ChatListResponse:
    """
    Список диалогов, свежие сверху.

    taken_over — перехвачен ли диалог кем угодно;
    mine — перехвачен именно текущим менеджером.
    """
    holder = aliased(Manager)
    stmt = select(Chat, holder).outerjoin(holder, Chat.taken_over_by_id == holder.id)
    count_stmt = select(func.count()).select_from(Chat)

    conditions = []
    if channel:
        conditions.append(Chat.channel == channel)
    if taken_over is not None:
        conditions.append(Chat.is_taken_over.is_(taken_over))
    if mine:
        conditions.append(Chat.taken_over_by_id == manager.id)
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(
                Chat.display_name.ilike(pattern),
                Chat.phone.ilike(pattern),
                Chat.external_id.ilike(pattern),
                Chat.username.ilike(pattern),
            )
        )
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int(db.execute(count_stmt).scalar_one())
    # NULLS LAST: чат без сообщений не должен всплывать наверх списка.
    stmt = stmt.order_by(Chat.last_message_at.desc().nullslast(), Chat.id.desc())
    rows = db.execute(stmt.limit(limit).offset(offset)).all()

    return ChatListResponse(total=total, items=[_chat_out(c, h) for c, h in rows])


@router.get("/chats/{chat_id}/messages", response_model=MessageListResponse, tags=["console"])
def list_messages(
    chat_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: Optional[int] = None,
    after_id: Optional[int] = None,
    _: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> MessageListResponse:
    """
    Сообщения диалога.

    before_id — листание вверх (история), after_id — инкрементальный опрос (поллинг).
    """
    if before_id is not None and after_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="before_id и after_id взаимоисключающи",
        )
    _get_chat_or_404(db, chat_id)

    author = aliased(Manager)
    base = select(ChatMessage, author.name).outerjoin(
        author, ChatMessage.author_manager_id == author.id
    ).where(ChatMessage.chat_id == chat_id)

    if after_id is not None:
        # Горячий путь поллинга: обычно возвращает ноль строк за доли миллисекунды.
        rows = db.execute(
            base.where(ChatMessage.id > after_id).order_by(ChatMessage.id.asc()).limit(limit)
        ).all()
        return MessageListResponse(items=[_message_out(m, n) for m, n in rows], has_more=False)

    if before_id is not None:
        base = base.where(ChatMessage.id < before_id)

    # Берём limit+1, чтобы узнать про has_more без отдельного COUNT.
    rows = db.execute(base.order_by(ChatMessage.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return MessageListResponse(items=[_message_out(m, n) for m, n in rows], has_more=has_more)


@router.post(
    "/chats/{chat_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["console"],
)
def mark_read(
    chat_id: int,
    _: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> Response:
    """Сбросить счётчик непрочитанных."""
    chat = _get_chat_or_404(db, chat_id)
    chat.unread_count = 0
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ──────────────────── Перехват и ответ ───────────────────── #

def _system_message(db: Session, chat_id: int, text_body: str) -> None:
    """Служебная плашка в треде — видна и менеджеру, и в истории."""
    db.add(
        ChatMessage(
            chat_id=chat_id,
            direction="out",
            author=AUTHOR_SYSTEM,
            text=text_body,
            msg_type="system",
        )
    )


@router.post("/chats/{chat_id}/takeover", response_model=ActionResponse, tags=["console"])
async def takeover_chat(
    chat_id: int,
    body: TakeoverRequest,
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> ActionResponse:
    """Взять диалог на себя — бот перестаёт отвечать этому клиенту."""
    chat = _get_chat_or_404(db, chat_id)

    if chat.is_taken_over and chat.taken_over_by_id not in (None, manager.id) and not body.force:
        holder = db.get(Manager, chat.taken_over_by_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Диалог уже ведёт {holder.name if holder else 'другой менеджер'}. "
                   f"Передайте force=true, чтобы перехватить.",
        )

    already_mine = chat.is_taken_over and chat.taken_over_by_id == manager.id
    chat.is_taken_over = True
    chat.taken_over_by_id = manager.id
    chat.taken_over_at = func.now()
    if not already_mine:
        _system_message(db, chat.id, f"Менеджер {manager.name} подключился к диалогу")
    db.commit()
    db.refresh(chat)
    logger.info("Перехват диалога %s менеджером %s", chat.id, manager.code)

    if body.notify_client and not already_mine:
        await chat_store.send_to_client(
            chat.channel,
            chat.external_id,
            f"К диалогу подключился менеджер {manager.name}.",
            manager_id=manager.id,
        )

    return ActionResponse(status="taken_over", chat=_chat_out(chat, manager))


@router.post("/chats/{chat_id}/release", response_model=ActionResponse, tags=["console"])
async def release_chat(
    chat_id: int,
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> ActionResponse:
    """Вернуть диалог боту."""
    chat = _get_chat_or_404(db, chat_id)
    if not chat.is_taken_over:
        return ActionResponse(status="already_released", chat=_chat_out(chat))

    chat.is_taken_over = False
    chat.taken_over_by_id = None
    chat.taken_over_at = None
    _system_message(db, chat.id, f"Менеджер {manager.name} вернул диалог боту")
    db.commit()
    db.refresh(chat)
    logger.info("Возврат диалога %s боту менеджером %s", chat.id, manager.code)
    return ActionResponse(status="released", chat=_chat_out(chat))


def _claim_for_reply(db: Session, chat: Chat, manager: Manager, take_over: bool) -> None:
    """Общая часть ответа текстом и файлом: проверка конфликта и перехват."""
    if chat.is_taken_over and chat.taken_over_by_id not in (None, manager.id):
        holder = db.get(Manager, chat.taken_over_by_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Диалог ведёт {holder.name if holder else 'другой менеджер'}",
        )

    # Перехват вместе с ответом: иначе бот ответит своё через несколько секунд,
    # и клиент получит два разных ответа на один вопрос.
    if take_over and not chat.is_taken_over:
        chat.is_taken_over = True
        chat.taken_over_by_id = manager.id
        chat.taken_over_at = func.now()
        _system_message(db, chat.id, f"Менеджер {manager.name} подключился к диалогу")
    elif chat.is_taken_over:
        # Диалог уже за этим менеджером — освежаем taken_over_at: он же служит
        # временем последней активности для таймера автовозврата
        # (chat_store.release_stale_takeovers, TAKEOVER_AUTO_RELEASE_MINUTES).
        chat.taken_over_at = func.now()
    db.commit()


@router.post("/chats/{chat_id}/reply", response_model=ActionResponse, tags=["console"])
async def reply_to_chat(
    chat_id: int,
    body: ReplyRequest,
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> ActionResponse:
    """Ответить клиенту от лица менеджера."""
    chat = _get_chat_or_404(db, chat_id)
    _claim_for_reply(db, chat, manager, body.take_over)

    # Отправка — вне транзакции. Запись сообщения делает сам транспортный хелпер
    # и только при успешной доставке.
    try:
        message_id = await chat_store.send_to_client(
            chat.channel, chat.external_id, body.text, manager_id=manager.id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if message_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось отправить сообщение клиенту. Попробуйте ещё раз.",
        )

    # Чтобы после /release бот не продолжил с места, где остановился,
    # и не начал противоречить менеджеру.
    try:
        if chat.channel == CHANNEL_WHATSAPP:
            from src.whatsapp_bot import whatsapp as wa

            wa._add_to_history(chat.external_id, "[менеджер подключился к диалогу]", body.text)
    except Exception as e:
        logger.warning("Не удалось добавить ответ менеджера в историю бота: %s", e)

    # Логируем идентификаторы, но НЕ текст — это переписка клиента.
    logger.info("Ответ менеджера %s в диалоге %s (message_id=%s)", manager.code, chat.id, message_id)

    db.refresh(chat)
    msg = db.get(ChatMessage, message_id)
    return ActionResponse(
        status="sent",
        chat=_chat_out(chat, manager if chat.is_taken_over else None),
        message=_message_out(msg, manager.name) if msg else None,
    )


@router.post("/chats/{chat_id}/reply-file", response_model=ActionResponse, tags=["console"])
async def reply_file_to_chat(
    chat_id: int,
    file: UploadFile = File(...),
    caption: str = Form("", max_length=1024),
    take_over: bool = Form(True),
    manager: Manager = Depends(get_current_manager),
    db: Session = Depends(get_chat_db),
) -> ActionResponse:
    """
    Отправить клиенту файл: фото, видео, аудио или документ.

    Gupshup принимает только ссылку на файл и скачивает его сам, поэтому файл
    сначала сохраняется на диск, а Gupshup получает часовую подписанную
    ссылку на внешний адрес приложения (DOMAIN / PUBLIC_BASE_URL).
    """
    from src.whatsapp_bot import whatsapp as wa

    chat = _get_chat_or_404(db, chat_id)
    if chat.channel != CHANNEL_WHATSAPP:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Отправка файлов поддерживается только в WhatsApp")

    base_url = media_store.public_base_url()
    if not base_url and not wa.WHATSAPP_DRY_RUN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не задан внешний адрес сервера (DOMAIN или PUBLIC_BASE_URL в .env) — "
                   "WhatsApp не сможет забрать файл",
        )

    # Читаем с потолком: не держать в памяти больше, чем WhatsApp всё равно примет.
    data = await file.read(media_store.OUT_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Файл пустой")
    file_name = Path((file.filename or "файл").replace("\\", "/")).name[:200] or "файл"
    mime = media_store.guess_mime(file_name, file.content_type)
    kind = media_store.classify_outgoing(mime)
    limit = media_store.OUT_LIMITS[kind]
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл больше {limit // (1024 * 1024)} МБ — WhatsApp такой не примет",
        )

    _claim_for_reply(db, chat, manager, take_over)

    media = await asyncio.to_thread(media_store.save_bytes, data, kind, file_name, mime)
    if media is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Не удалось сохранить файл на сервере")

    url = (base_url or "") + media_store.signed_path_url(media["media_path"])
    message_id = await wa._send_whatsapp_media(
        chat.external_id,
        kind,
        url,
        media=media,
        caption=caption.strip(),
        file_name=file_name,
        persist_manager_id=manager.id,
    )
    if message_id is None:
        media_store.delete(media["media_path"])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось отправить файл клиенту. Попробуйте ещё раз.",
        )

    try:
        wa._add_to_history(chat.external_id, "[менеджер подключился к диалогу]",
                           f"[менеджер отправил файл: {file_name}] {caption}".strip())
    except Exception as e:
        logger.warning("Не удалось добавить файл менеджера в историю бота: %s", e)

    logger.info("Файл от менеджера %s в диалоге %s (message_id=%s, kind=%s, size=%s)",
                manager.code, chat.id, message_id, kind, len(data))

    db.refresh(chat)
    msg = db.get(ChatMessage, message_id)
    return ActionResponse(
        status="sent",
        chat=_chat_out(chat, manager if chat.is_taken_over else None),
        message=_message_out(msg, manager.name) if msg else None,
    )


# ──────────────────── Статистика (только директор) ──────────── #
# "Заявка" в этой статистике = диалог (Chat). Ничего нового в БД не заводим —
# считаем по уже существующим chats/chat_messages.

_STATS_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)  # синоним «без нижней границы» для period=all


def _parse_stat_date(raw: str, *, end_of_day: bool = False) -> datetime:
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неверный формат даты: {raw!r}, ожидается YYYY-MM-DD",
        )
    d = d.replace(tzinfo=timezone.utc)
    return d + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else d


def _stats_period_bounds(
    period: str, date_from: Optional[str], date_to: Optional[str]
) -> Tuple[datetime, datetime]:
    """date_from/date_to (хотя бы один) переопределяют period; иначе — скользящее окно."""
    now = datetime.now(timezone.utc)
    if date_from or date_to:
        start = _parse_stat_date(date_from) if date_from else _STATS_EPOCH
        end = _parse_stat_date(date_to, end_of_day=True) if date_to else now
        return start, end
    starts = {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "all": _STATS_EPOCH,
    }
    return starts.get(period, now - timedelta(days=7)), now


@router.get("/stats", response_model=StatsResponse, tags=["console"])
def get_stats(
    period: str = Query(default="week", description="today | week | month | all"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD, переопределяет period"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD, переопределяет period"),
    _: Manager = Depends(require_director),
    db: Session = Depends(get_chat_db),
) -> StatsResponse:
    """
    Статистика по заявкам за период: сколько всего, сколько без ответа/непрочитанных,
    и сколько заявок обработал каждый менеджер. Доступно только руководителю.
    """
    start, end = _stats_period_bounds(period, date_from, date_to)

    in_period = (Chat.created_at >= start, Chat.created_at <= end)

    total_chats = int(
        db.execute(select(func.count()).select_from(Chat).where(*in_period)).scalar_one()
    )

    unread_chats = int(
        db.execute(
            select(func.count()).select_from(Chat).where(*in_period, Chat.unread_count > 0)
        ).scalar_one()
    )

    replied_chat_ids = select(ChatMessage.chat_id).where(ChatMessage.author == AUTHOR_MANAGER)
    never_replied_chats = int(
        db.execute(
            select(func.count()).select_from(Chat).where(
                *in_period, Chat.id.notin_(replied_chat_ids)
            )
        ).scalar_one()
    )

    # По менеджерам: сколько РАЗНЫХ заявок за период каждый обработал (ответил хотя бы раз).
    # LEFT JOIN дважды, чтобы менеджеры без единого ответа тоже попали в выдачу с нулём —
    # директору важно видеть и тех, кто ничего не обработал.
    counted = aliased(Chat)
    by_manager_rows = db.execute(
        select(Manager.id, Manager.name, func.count(func.distinct(counted.id)).label("chats_handled"))
        .select_from(Manager)
        .outerjoin(
            ChatMessage,
            (ChatMessage.author_manager_id == Manager.id) & (ChatMessage.author == AUTHOR_MANAGER),
        )
        .outerjoin(
            counted,
            (counted.id == ChatMessage.chat_id) & (counted.created_at >= start) & (counted.created_at <= end),
        )
        .group_by(Manager.id, Manager.name)
        .order_by(func.count(func.distinct(counted.id)).desc(), Manager.name)
    ).all()

    return StatsResponse(
        period_from=start,
        period_to=end,
        total_chats=total_chats,
        unread_chats=unread_chats,
        never_replied_chats=never_replied_chats,
        by_manager=[
            ManagerStatEntry(manager_id=r[0], manager_name=r[1], chats_handled=int(r[2]))
            for r in by_manager_rows
        ],
    )


@router.get("/media/{message_id}", tags=["console"])
def get_media(
    message_id: int,
    exp: int = Query(...),
    sig: str = Query(..., max_length=128),
    db: Session = Depends(get_chat_db),
) -> FileResponse:
    """
    Отдаёт вложение сообщения по подписанной ссылке из /chats/{id}/messages.

    Без JWT намеренно: <img>/<video>/<audio> не умеют слать Authorization.
    Доступ даёт подпись, которую получает только вошедший менеджер
    (см. src/common/media_store.py). На любую проблему — один и тот же 404,
    чтобы перебором id нельзя было узнать, у каких сообщений есть файлы.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    if not media_store.verify_signature(message_id, exp, sig):
        raise not_found
    msg = db.get(ChatMessage, message_id)
    extra = msg.extra if msg is not None and isinstance(msg.extra, dict) else {}
    path = media_store.resolve_path(extra.get("media_path") or "") if extra.get("media_path") else None
    if path is None:
        raise not_found
    return _file_response(path, extra.get("media_mime"), msg.file_name)


@router.get("/media-out", tags=["console"])
def get_outgoing_media(
    p: str = Query(..., max_length=300),
    exp: int = Query(...),
    sig: str = Query(..., max_length=128),
) -> FileResponse:
    """
    Файл, который менеджер отправляет клиенту, — отсюда его забирает Gupshup.
    Ссылка подписана по пути файла и живёт час (media_store.signed_path_url).
    """
    path = media_store.resolve_path(p) if media_store.verify_path_signature(p, exp, sig) else None
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return _file_response(path, mimetypes.guess_type(path.name)[0], None)


def _file_response(path: Path, mime: Optional[str], file_name: Optional[str]) -> FileResponse:
    mime = (mime or "application/octet-stream").lower()
    # MIME присылает клиент. Всё, что браузер мог бы исполнить на домене
    # консоли (HTML, SVG, XML…), отдаём только на скачивание — иначе клиент
    # прислал бы «документ» со скриптом и угнал сессию менеджера.
    inline = mime in _INLINE_MIME or mime.startswith(("video/", "audio/"))
    return FileResponse(
        path,
        media_type=(mime if inline else "application/octet-stream"),
        filename=(file_name or path.name),
        content_disposition_type=("inline" if inline else "attachment"),
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


_INLINE_MIME = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf",
})
