from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.v1 import endpoints
from src.db.database import Base, engine
from src.db.Models import product_models as _product_models  # важно импортировать модели до create_all
from src.telegram_bot.bot import start_bot, stop_bot

try:
    from src.whatsapp_bot import whatsapp as whatsapp_bot
    _WHATSAPP_AVAILABLE = True
except ModuleNotFoundError:
    whatsapp_bot = None
    _WHATSAPP_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    await start_bot()
    yield
    await stop_bot()


app = FastAPI(title="GQ API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(endpoints.router, prefix="/api/v1")

if _WHATSAPP_AVAILABLE:
    app.include_router(whatsapp_bot.router, prefix="/api/v1")
