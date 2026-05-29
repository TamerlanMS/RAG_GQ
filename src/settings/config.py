import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY not found in environment variables")

if not os.getenv("PINECONE_API_KEY"):
    raise ValueError("PINECONE_API_KEY not found in environment variables")

if not os.getenv("API_TOKEN"):
    raise ValueError("API_TOKEN not found in environment variables")

if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
    import warnings
    warnings.warn(
        "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram notifications will be disabled.",
        RuntimeWarning,
        stacklevel=1,
    )


def _get_system_prompt() -> str:
    file_path = Path(__file__).resolve().parent / "system_prompt.txt"

    if not file_path.exists():
        raise FileNotFoundError(f"Файл {file_path} не найден.")

    with open(file_path, "r", encoding="utf-8") as f:
        sys_prompt = f.read()

    return sys_prompt


AGENT_PROMPT = _get_system_prompt()
MAX_HISTORY_LENGTH = 15


class OpenAIModel(BaseModel):
    """Базовый класс для языковой модели OpenAI."""

    openai_api_key: Optional[str] = Field(
        default=os.getenv("OPENAI_API_KEY"), description="API-ключ OpenAI"
    )
    timeout: Optional[int] = Field(default=5, description="Таймаут запроса в секундах")


class LLMSettings(OpenAIModel):
    """Конфигурация для языковой модели OpenAI."""

    chat_model: str = Field(
        default="gpt-4o", description="Название модели для чата"
    )
    temperature: float = Field(
        default=0.2, ge=0.0, le=1.0, description="Креативность модели"
    )
    max_tokens: Optional[int] = Field(
        default=1024, description="Максимальное число токенов в ответе"
    )
    system_prompt: Optional[str] = Field(
        default=AGENT_PROMPT, description="Системный промпт для модели"
    )


class PineconeSettings(BaseModel):
    """Индекс наименований товаров (русскоязычные описания)."""

    dimension: int = Field(default=1536, description="Размерность эмбеддинга")
    index_name: str = Field(
        default=os.getenv("PINECONE_NAMES_INDEX_NAME", "gq-names"),
        description="Название индекса наименований в Pinecone",
    )
    index_host: str = Field(
        default=os.getenv("PINECONE_NAMES_INDEX_HOST", "https://gq-names-rkhbx77.svc.apu-57e2-42f6.pinecone.io"),
        description="Хост индекса наименований в Pinecone",
    )
    namespace: str = Field(
        default="names", description="Namespace для наименований"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Модель эмбеддинга"
    )
    openai_api_key: Optional[str] = Field(
        default=os.getenv("OPENAI_API_KEY"), description="API-ключ OpenAI"
    )
    pinecone_api_key: Optional[str] = Field(
        default=os.getenv("PINECONE_API_KEY"), description="API-ключ Pinecone"
    )
    chunk_size: int = Field(default=200, description="Размер чанка")
    chunk_overlap: int = Field(default=50, description="Пересечение чанков")
    search_k: int = Field(default=10, description="Количество результатов поиска")


class PineconeArticulSettings(BaseModel):
    """Индекс артикулов товаров (короткие коды: PP24-1UC5ES-D05, A9D31620 и т.д.)."""

    dimension: int = Field(default=1536, description="Размерность эмбеддинга")
    index_name: str = Field(
        default=os.getenv("PINECONE_ARTICUL_INDEX_NAME", "gq-articuls"),
        description="Название индекса артикулов в Pinecone",
    )
    index_host: str = Field(
        default=os.getenv("PINECONE_ARTICUL_INDEX_HOST", "https://gq-articuls-rkhbx77.svc.apu-57e2-42f6.pinecone.io"),
        description="Хост индекса артикулов в Pinecone",
    )
    namespace: str = Field(
        default="articuls", description="Namespace для артикулов"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Модель эмбеддинга"
    )
    openai_api_key: Optional[str] = Field(
        default=os.getenv("OPENAI_API_KEY"), description="API-ключ OpenAI"
    )
    pinecone_api_key: Optional[str] = Field(
        default=os.getenv("PINECONE_API_KEY"), description="API-ключ Pinecone"
    )
    search_k: int = Field(default=5, description="Количество результатов поиска")
