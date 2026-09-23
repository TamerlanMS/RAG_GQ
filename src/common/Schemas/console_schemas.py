"""Pydantic-схемы менеджерской веб-консоли."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from src.common.auth import BCRYPT_MAX_BYTES


def _validate_password(v: str) -> str:
    if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError("Пароль слишком длинный (максимум 72 байта)")
    return v


# ─── Авторизация ─────────────────────────────────────────────

class LoginRequest(BaseModel):
    phone: str = Field(..., description="Телефон в любом формате: 87750866676, +7 775 086-66-76")
    password: str = Field(..., min_length=1, description="Пароль")


class ManagerOut(BaseModel):
    id: int
    code: str
    name: str
    role: str
    phone: str

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    manager: ManagerOut


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Минимум 8 символов")

    @field_validator("new_password")
    @classmethod
    def _check_new(cls, v: str) -> str:
        return _validate_password(v)


# ─── Чаты ────────────────────────────────────────────────────

class TakenOverBy(BaseModel):
    id: int
    name: str


class ChatOut(BaseModel):
    id: int
    channel: str
    external_id: str
    display_name: Optional[str] = None
    phone: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread_count: int
    is_taken_over: bool
    taken_over_by: Optional[TakenOverBy] = None


class ChatListResponse(BaseModel):
    total: int
    items: List[ChatOut]


class MessageOut(BaseModel):
    id: int
    direction: str
    author: str
    author_manager_name: Optional[str] = None
    text: Optional[str] = None
    msg_type: str
    file_name: Optional[str] = None
    # Подписанная ссылка на скачанное вложение (см. src/common/media_store.py).
    # None — у сообщения нет файла или скачать его у Gupshup не удалось.
    media_url: Optional[str] = None
    media_mime: Optional[str] = None
    media_size: Optional[int] = None
    created_at: datetime

    # extra наружу намеренно не отдаём: там служебная кухня (combined_prompt, vision),
    # менеджеру это шум.


class MessageListResponse(BaseModel):
    items: List[MessageOut]
    has_more: bool = False


# ─── Действия ────────────────────────────────────────────────

class ReplyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    take_over: bool = Field(
        default=True,
        description=(
            "Перехватить диалог вместе с отправкой. По умолчанию да — иначе бот "
            "ответит своё через несколько секунд, и клиент получит два разных ответа."
        ),
    )


class TakeoverRequest(BaseModel):
    force: bool = Field(default=False, description="Перехватить, даже если чат держит другой менеджер")
    notify_client: bool = Field(default=False, description="Сообщить клиенту о подключении менеджера")


class ActionResponse(BaseModel):
    status: str
    chat: ChatOut
    message: Optional[MessageOut] = None


# ─── Статистика по заявкам (только для директора) ─────────────

class ManagerStatEntry(BaseModel):
    manager_id: int
    manager_name: str
    chats_handled: int = Field(..., description="Заявок за период, где менеджер ответил хотя бы раз")


class StatsResponse(BaseModel):
    period_from: datetime
    period_to: datetime
    total_chats: int = Field(..., description="Заявок (диалогов), созданных за период")
    unread_chats: int = Field(..., description="Из них — с непрочитанными сообщениями сейчас")
    never_replied_chats: int = Field(..., description="Из них — без единого ответа менеджера")
    by_manager: List[ManagerStatEntry]
