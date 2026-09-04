"""
Модели переписки для менеджерской веб-консоли.

Живут в отдельной базе (ChatBase / chat_engine), см. src/db/chat_database.py.

Класс сообщения называется ChatMessage, а не Message: имя Message уже занято
aiogram.types.Message, и коллизия вылезла бы в самых чувствительных местах.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db.chat_database import ChatBase

# Каналы
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_TELEGRAM = "telegram"

# Направления
DIRECTION_IN = "in"
DIRECTION_OUT = "out"

# Авторы
AUTHOR_CLIENT = "client"
AUTHOR_BOT = "bot"
AUTHOR_MANAGER = "manager"
AUTHOR_SYSTEM = "system"


class Chat(ChatBase):
    """
    Диалог с одним клиентом.

    Личность клиента унифицирована через пару (channel, external_id), потому что
    у каналов разные естественные ключи: WhatsApp — номер телефона, Telegram — user_id.
    """

    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_chat_channel_external"),
        Index("ix_chats_last_message_at", "last_message_at"),
    )

    id = Column(Integer, primary_key=True)

    channel = Column(String(16), nullable=False)

    # ВАЖНО: для WhatsApp здесь лежит СЫРАЯ строка от Gupshup ("77789392009").
    # Именно она уходит в поле destination при отправке (_send_whatsapp).
    # Нормализованный вид — в колонке phone, и он служит только для поиска/отображения.
    external_id = Column(String(64), nullable=False)

    # Заложено под будущее подключение Telegram: create_all не делает ALTER,
    # добавить колонку потом = ручная миграция на проде.
    tg_chat_id = Column(BigInteger, nullable=True)
    username = Column(String(100), nullable=True)

    display_name = Column(String(200), nullable=True)
    phone = Column(String(20), nullable=True, index=True)

    # Денормализация ради списка чатов: рисуется одним индексным сканом, без N+1.
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    last_message_preview = Column(String(300), nullable=True)
    unread_count = Column(Integer, nullable=False, default=0, server_default="0")

    # Перехват: пока True — бот не отвечает этому клиенту.
    is_taken_over = Column(Boolean, nullable=False, default=False, server_default="false")
    taken_over_by_id = Column(Integer, ForeignKey("managers.id"), nullable=True)
    taken_over_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Chat {self.channel}:{self.external_id}>"


class ChatMessage(ChatBase):
    """Одно сообщение в диалоге."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        # Обслуживает и пагинацию треда, и инкрементальный поллинг (chat_id=? AND id > ?).
        Index("ix_chat_messages_chat_id_id", "chat_id", "id"),
        # Дедупликация переотправленных вебхуков Gupshup.
        # Partial: у сообщений менеджера и системных external_id = NULL,
        # и они не должны конфликтовать между собой.
        Index(
            "uq_chat_messages_external",
            "chat_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    # BigInteger PK в Postgres даёт BIGSERIAL. Монотонный id — это курсор для
    # after_id/before_id: сортировка по нему стабильна, в отличие от created_at,
    # где сообщения одной пачки получат одинаковый now().
    id = Column(BigInteger, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)

    direction = Column(String(3), nullable=False)
    author = Column(String(16), nullable=False)
    author_manager_id = Column(Integer, ForeignKey("managers.id"), nullable=True)

    text = Column(Text, nullable=True)
    msg_type = Column(String(16), nullable=False, default="text")

    file_name = Column(String(300), nullable=True)
    media_url = Column(Text, nullable=True)

    # wamid для WhatsApp. NULL у сообщений менеджера и системных.
    external_id = Column(String(128), nullable=True)

    # Колонка НЕ может называться metadata — это зарезервированный атрибут
    # declarative-класса SQLAlchemy, объявление уронило бы импорт модуля.
    extra = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<ChatMessage {self.id} chat={self.chat_id} {self.direction}/{self.author}>"
