"""
Аутентификация менеджеров веб-консоли: bcrypt + JWT.

Секрет подписи — переменная API_TOKEN. Она уже обязательна (src/settings/config.py),
но до появления консоли нигде не использовалась.

Два следствия, которые важно понимать:
  - значение должно быть высокоэнтропийным;
  - его ротация разлогинивает всех менеджеров разом.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.common.logger import logger
from src.db.chat_database import get_chat_db
from src.db.Models.manager_models import Manager

JWT_SECRET: str = os.getenv("API_TOKEN", "")
JWT_ALG = "HS256"
JWT_TTL_HOURS: int = int(os.getenv("CONSOLE_JWT_TTL_HOURS", "12"))

if len(JWT_SECRET) < 32:
    logger.warning(
        "API_TOKEN короче 32 символов — он используется как секрет подписи JWT "
        'веб-консоли. Задайте случайное значение: python -c "import secrets; '
        'print(secrets.token_urlsafe(48))"'
    )

# bcrypt молча отбрасывает всё после 72 байт — валидируем длину на входе.
BCRYPT_MAX_BYTES = 72

# Хеш-пустышка для защиты от тайминг-атаки: при неизвестном телефоне всё равно
# выполняем checkpw, иначе разница во времени ответа (~250 мс) выдаёт, какие
# номера зарегистрированы. Номера менеджеров лежат в git открытым текстом.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-constant-time", bcrypt.gensalt(rounds=12))


# ─── Пароли ──────────────────────────────────────────────────

def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def burn_dummy_hash() -> None:
    """Холостая проверка пароля — выравнивает время ответа при неизвестном телефоне."""
    bcrypt.checkpw(b"whatever", _DUMMY_HASH)


# ─── JWT ─────────────────────────────────────────────────────

def create_access_token(manager: Manager) -> Tuple[str, int]:
    """Возвращает (токен, время жизни в секундах)."""
    now = datetime.now(timezone.utc)
    expires_in = JWT_TTL_HOURS * 3600
    payload: Dict[str, Any] = {
        "sub": str(manager.id),
        "code": manager.code,
        "phone": manager.phone,
        "name": manager.name,
        "role": manager.role,
        "iat": now,
        "exp": now + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG), expires_in


# HTTPBearer, а не OAuth2PasswordBearer: единственный плюс второго — кнопка
# Authorize в Swagger, а Swagger в этом приложении отключён (main.py, docs_url=None).
_bearer = HTTPBearer(auto_error=False)


def get_current_manager(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_chat_db),
) -> Manager:
    """Зависимость: достаёт менеджера из Bearer-токена."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if cred is None or cred.scheme.lower() != "bearer":
        raise unauthorized

    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия истекла, войдите заново",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise unauthorized

    try:
        manager_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise unauthorized

    manager = db.get(Manager, manager_id)
    if manager is None or not manager.is_active:
        raise unauthorized
    return manager


# ─── Ограничение перебора на логине ──────────────────────────
# Приложение однопроцессное (uvicorn без --workers, см. Dockerfile),
# поэтому счётчика в памяти достаточно.

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 15 * 60
_login_attempts: Dict[str, Tuple[int, float]] = {}


def check_login_rate(phone: str) -> None:
    """Бросает 429, если по номеру слишком много неудачных попыток."""
    count, first_ts = _login_attempts.get(phone, (0, 0.0))
    if count >= _LOGIN_MAX_ATTEMPTS and (time.monotonic() - first_ts) < _LOGIN_WINDOW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много неудачных попыток входа. Попробуйте через 15 минут.",
        )


def register_failed_login(phone: str) -> None:
    count, first_ts = _login_attempts.get(phone, (0, 0.0))
    now = time.monotonic()
    if count == 0 or (now - first_ts) >= _LOGIN_WINDOW_SECONDS:
        _login_attempts[phone] = (1, now)
    else:
        _login_attempts[phone] = (count + 1, first_ts)


def reset_login_attempts(phone: str) -> None:
    _login_attempts.pop(phone, None)
