"""
Модель менеджера — логин в веб-консоль по телефону и паролю.

Живёт в отдельной базе переписки (ChatBase), потому что на неё ссылаются
внешними ключами chats.taken_over_by_id и chat_messages.author_manager_id,
а межбазовых FK в Postgres не существует.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from src.db.chat_database import ChatBase


class Manager(ChatBase):
    """Менеджер, имеющий доступ к веб-консоли."""

    __tablename__ = "managers"

    id = Column(Integer, primary_key=True)

    # Стабильный ключ для сидирования из config.MANAGERS: телефон может смениться, code — нет.
    code = Column(String(50), unique=True, nullable=False)

    name = Column(String(200), nullable=False)
    role = Column(String(100), nullable=False, default="Менеджер по продажам")

    # Логин. Всегда нормализован через src.common.phone.normalize_phone → +7XXXXXXXXXX.
    phone = Column(String(20), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)

    # Строкой, а не BigInteger: в config.MANAGER_CHAT_IDS допустимы и @username.
    tg_chat_id = Column(String(50), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Manager {self.code} {self.phone}>"
