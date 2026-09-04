"""
Нормализация казахстанских номеров телефона.

Модуль намеренно лёгкий — без LangChain, Pinecone и прочих тяжёлых импортов,
потому что используется в пути логина менеджера (src/common/auth.py)
и в персистентности чатов (src/common/chat_store.py).
"""
from __future__ import annotations

import re
from typing import Optional

_NON_DIGIT_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> Optional[str]:
    """
    Приводит казахстанский номер к формату +7XXXXXXXXXX.

    Принимает любые разделители и оба префикса — международный «7» и домашний «8»:
        +77710010254        -> +77710010254
        87750866676         -> +77750866676
        8 (771) 166-82-84   -> +77711668284
        +87711668284        -> +77711668284   (домашний 8XXX с приписанным «+»)
        77789392009         -> +77789392009   (сырой формат номера от Gupshup)
        7086110592          -> +77086110592   (10 цифр без префикса)

    Возвращает None, если номер не распознан.
    """
    digits = _NON_DIGIT_RE.sub("", raw or "")

    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return None

    return f"+{digits}"
