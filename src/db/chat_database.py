"""
Подключение к отдельной базе переписки (менеджерская веб-консоль).

Зачем отдельная база, а не таблицы в основной:
  - `DELETE /api/v1/drop_DB` вызывает `Base.metadata.drop_all` и сносит всю схему.
    Переписку с клиентами восстановить нечем (товары можно перезалить из 1С),
    поэтому она живёт под своим `ChatBase` в своей базе — drop_all до неё не дотянется.
  - Бэкапить и выдавать доступ к ней можно отдельно от товарного контура.

Всё здесь — зеркало src/db/database.py, только для другой базы.
"""
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.common.logger import logger
from src.settings.db_settings import settings

ChatBase = declarative_base()

chat_engine = create_engine(
    settings.CHAT_DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

ChatSessionLocal = sessionmaker(bind=chat_engine, autoflush=False, autocommit=False)


def get_chat_db() -> Generator[Session, None, None]:
    """Зависимость FastAPI для роутов консоли."""
    db = ChatSessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_chat_database() -> None:
    """
    Идемпотентно создаёт базу переписки, если её ещё нет.

    Нужно потому, что POSTGRES_DB в docker-compose создаёт ровно одну базу,
    а скрипты из /docker-entrypoint-initdb.d/ выполняются только при пустом
    каталоге данных — на существующем pgdata/ они не отработают никогда.
    """
    # isolation_level="AUTOCOMMIT" обязателен: CREATE DATABASE
    # не выполняется внутри транзакционного блока.
    admin_engine = create_engine(
        settings.ADMIN_DATABASE_URL,
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": settings.CHAT_DB_NAME},
            ).scalar()
            if exists:
                return
            # Имя берётся из конфига, не из пользовательского ввода.
            conn.execute(text(f'CREATE DATABASE "{settings.CHAT_DB_NAME}"'))
            logger.info("Создана база переписки: %s", settings.CHAT_DB_NAME)
    finally:
        admin_engine.dispose()
