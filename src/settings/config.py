import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY not found in environment variables")

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

# ─── Менеджеры ───────────────────────────────────────────────
MANAGERS = [
    {
        "id": "director",
        "name": "Ермекбаева Арна Ордаевна",
        "role": "Руководитель",
        "phone": "+77710010254",
    },
    {
        "id": "kalbaeva",
        "name": "Калбаева Диана Серикболовна",
        "role": "Менеджер по продажам",
        "phone": "+77750866676",
    },
    {
        "id": "sabieva",
        "name": "Сабиева Гульнара Джаксыкельдиновна",
        "role": "Менеджер по продажам",
        "phone": "+87711668284",
    },
    {
        "id": "zhenibek",
        "name": "Жиенбек Заманбек Манасбайұлы",
        "role": "Менеджер по продажам",
        "phone": "+87007718216",
    },
    {
        "id": "dolakov",
        "name": "Долаков Дауд Ибрагимович",
        "role": "Менеджер по продажам",
        "phone": "+87086110592",
    },
]

# Telegram chat_id каждого менеджера (числовые ID или @username).
# В тестовом режиме все сообщения идут на TELEGRAM_TEST_CHAT_ID.
MANAGER_CHAT_IDS: dict = {
    "director": os.getenv("TG_CHAT_ID_DIRECTOR", ""),
    "kalbaeva": os.getenv("TG_CHAT_ID_KALBAEVA", ""),
    "sabieva":  os.getenv("TG_CHAT_ID_SABIEVA", ""),
    "zhenibek": os.getenv("TG_CHAT_ID_ZHENIBEK", ""),
    "dolakov":  os.getenv("TG_CHAT_ID_DOLAKOV", ""),
}

# Тестовый режим: все уведомления идут на один чат (например @LoginZ_B).
# Отключить, когда у каждого менеджера будет свой TG_CHAT_ID_*.
TELEGRAM_TEST_MODE: bool = os.getenv("TELEGRAM_TEST_MODE", "true").lower() == "true"
TELEGRAM_TEST_CHAT_ID: str = os.getenv("TELEGRAM_TEST_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))


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
