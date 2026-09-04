from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):  # type: ignore
    """Settings for the application."""

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASS: str
    DB_NAME: str

    # Отдельная база под переписку менеджерской веб-консоли.
    # Живёт в том же кластере Postgres, но со своим engine и своим ChatBase —
    # поэтому DELETE /api/v1/drop_DB (Base.metadata.drop_all) до неё не дотягивается.
    CHAT_DB_NAME: str = "gq_chat"

    class Config:
        extra = "ignore"

    @property
    def _DSN_PREFIX(self) -> str:
        return f"{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        # postgres+psycopg://user:password@host:port/dbname
        return f"postgresql+asyncpg://{self._DSN_PREFIX}/{self.DB_NAME}"

    @property
    def SYNC_DATABASE_URL(self) -> str:
        # postgres+psycopg://user:password@host:port/dbname
        return f"postgresql+psycopg://{self._DSN_PREFIX}/{self.DB_NAME}"

    @property
    def CHAT_DATABASE_URL(self) -> str:
        """Подключение к базе переписки."""
        return f"postgresql+psycopg://{self._DSN_PREFIX}/{self.CHAT_DB_NAME}"

    @property
    def ADMIN_DATABASE_URL(self) -> str:
        """Служебное подключение к базе postgres — нужно только для CREATE DATABASE."""
        return f"postgresql+psycopg://{self._DSN_PREFIX}/postgres"


settings = Settings()
