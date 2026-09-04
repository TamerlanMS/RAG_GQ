import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.v1 import console, endpoints
from src.common.logger import logger
from src.common.middlewares import register_middlewares
from src.db.chat_database import ChatBase, chat_engine, ensure_chat_database
from src.db.database import Base, engine
from src.db.Models import product_models as _product_models  # важно импортировать модели до create_all

# Модели веб-консоли. Наследуют ChatBase (не Base) и живут в отдельной базе —
# импорт нужен, чтобы ChatBase.metadata их увидел до create_all.
# В src/db/Models/__init__.py их намеренно НЕ экспортируем: попадание в Base
# означало бы, что DELETE /api/v1/drop_DB снесёт всю переписку.
from src.db.Models import chat_models as _chat_models  # noqa: F401
from src.db.Models import manager_models as _manager_models  # noqa: F401
from src.telegram_bot.bot import start_bot, stop_bot

try:
    from src.whatsapp_bot import whatsapp as whatsapp_bot
    _WHATSAPP_AVAILABLE = True
except ModuleNotFoundError:
    whatsapp_bot = None
    _WHATSAPP_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_chat_database()
    ChatBase.metadata.create_all(bind=chat_engine)
    Base.metadata.create_all(bind=engine)
    await start_bot()
    yield
    await stop_bot()


app = FastAPI(title="GQ API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
register_middlewares(app)
app.include_router(endpoints.router, prefix="/api/v1")
app.include_router(console.router, prefix="/api/v1")

if _WHATSAPP_AVAILABLE:
    app.include_router(whatsapp_bot.router, prefix="/api/v1")

# Собранный фронтенд веб-консоли.
# Лежит ВНЕ /app намеренно: docker-compose монтирует репозиторий в /app и перекрыл бы
# содержимое, собранное на этапе сборки образа.
# Проверка is_dir() обязательна — StaticFiles с несуществующим каталогом падает
# на старте, а приложение должно подниматься при отсутствии необязательной части
# (тот же приём, что для Pinecone, aiogram и whatsapp).
class _ConsoleStatic(StaticFiles):
    """
    index.html не кешируется, ассеты — кешируются навсегда.

    Без этого браузер менеджера после обновления консоли продолжает держать
    старый index.html и, значит, ссылку на старый бандл — обновление молча
    не доезжает. Имена ассетов содержат хеш содержимого (Vite), поэтому для
    них immutable-кеш безопасен.
    """

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        if path.endswith(".html") or path in ("", ".", "/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "assets/" in path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


_console_dir = Path(os.getenv("CONSOLE_DIST_DIR", "/srv/console"))
if _console_dir.is_dir():
    app.mount("/console", _ConsoleStatic(directory=str(_console_dir), html=True), name="console")
    logger.info("Веб-консоль смонтирована на /console (из %s)", _console_dir)
else:
    logger.warning("Каталог консоли %s не найден — веб-консоль не смонтирована", _console_dir)
