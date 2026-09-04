import logging
import os
import time
from typing import Callable, Awaitable

from fastapi import Request, Response, FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.common.logger import logger


async def debug_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_body = await request.body()
    request.state.raw_body = request_body

    # Считаем чистое время ответа
    start_time = time.perf_counter()
    response = await call_next(request)
    response_process_time = round(time.perf_counter() - start_time, 3)

    # Считываем тело ответа и собираем заново
    resp_body = b""
    async for chunk in response.body_iterator:  # type: ignore
        resp_body += chunk

    response_body = resp_body.decode("utf-8", errors="ignore")

    response = Response(
        content=resp_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
    # Логируем запрос и ответ

    body = request_body.decode("utf-8", errors="ignore")
    logger.debug(
        "--> Request from %s %s to %s - request body: %s",
        request.client,
        request.method,
        request.url,
        body,
    )
    logger.debug(
        "<-- Response took %s seconds - response body: %s",
        response_process_time,
        response_body,
    )

    return response


async def log_new_request_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if logger.isEnabledFor(logging.DEBUG):
        return await debug_middleware(request, call_next)
    logger.info(
        "Request from %s %s to %s",
        request.client,
        request.method,
        request.url,
    )
    return await call_next(request)


def register_middlewares(app: FastAPI) -> None:
    # ВНИМАНИЕ: log_new_request_middleware намеренно НЕ подключён.
    # При logger.setLevel(DEBUG) он делегирует в debug_middleware, который
    # вычитывает response.body_iterator целиком и пересобирает Response. Это
    #   (а) ломает StreamingResponse/FileResponse — то есть раздачу веб-консоли;
    #   (б) пишет тела всех ответов в logs/app.log, включая JWT из /console/login
    #       и всю переписку клиентов из /console/chats/{id}/messages.
    # Если понадобится логирование запросов — включать только INFO-ветку.
    # app.middleware("http")(log_new_request_middleware)

    # allow_origins=["*"] вместе с allow_credentials=True браузеры отвергают
    # по спецификации — такая настройка не «нестрогая», она нерабочая.
    # Здесь: явный список origin-ов, credentials не нужны (токен идёт заголовком).
    origins = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
