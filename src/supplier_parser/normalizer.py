"""Утилиты нормализации данных прайса."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


_NONE_VALS = {"none", "null", "н/д", "-", "", "#н/д", "n/a"}


def clean_str(value) -> Optional[str]:
    """None/пустые значения → None, иначе нормализованная строка."""
    if value is None:
        return None
    if isinstance(value, float) and value == int(value):
        value = int(value)
    s = unicodedata.normalize("NFKC", str(value)).strip()
    s = re.sub(r"\s+", " ", s)
    if s.lower() in _NONE_VALS:
        return None
    return s


def clean_price(value) -> Optional[float]:
    """Числовое значение → float, None если не валидно."""
    if value is None:
        return None
    try:
        f = float(value)
        if f <= 0:
            return None
        return round(f, 2)
    except (ValueError, TypeError):
        s = str(value).strip().replace(" ", "").replace(",", ".")
        try:
            f = float(s)
            return round(f, 2) if f > 0 else None
        except ValueError:
            return None


def clean_unit(value) -> str:
    """Нормализация единиц измерения."""
    s = clean_str(value)
    if not s:
        return "шт"
    unit_map = {
        "шт": "шт", "штука": "шт", "штуки": "шт", "за штуку": "шт",
        "м": "м", "метр": "м", "метры": "м", "метров": "м",
        "кг": "кг", "кг.": "кг",
        "уп": "уп", "упак": "уп", "упаковка": "уп",
        "комплект": "комп", "комп": "комп",
        "м2": "м2", "м3": "м3",
        "рул": "рул", "рулон": "рул",
        "шт.": "шт", "м.": "м",
    }
    return unit_map.get(s.lower(), s)


def clean_int(value) -> Optional[int]:
    """Числовое значение → int."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def price_excl_vat(price_with_vat: float, vat_rate: float = 12.0) -> float:
    """Цена с НДС → без НДС."""
    return round(price_with_vat / (1 + vat_rate / 100), 2)


def price_incl_vat(price_excl: float, vat_rate: float = 12.0) -> float:
    """Цена без НДС → с НДС."""
    return round(price_excl * (1 + vat_rate / 100), 2)
