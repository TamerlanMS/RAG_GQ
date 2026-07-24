"""Pydantic-схема нормализованного товара от поставщика."""
from __future__ import annotations

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re


class SupplierProduct(BaseModel):
    supplier_code: str
    article: str
    name: str
    name_full: Optional[str] = None
    unit: str = "шт"
    price_base: float                    # без НДС
    price_with_vat: Optional[float] = None
    currency: str = "KZT"
    vat_rate: float = 12.0
    pack_qty: Optional[int] = None
    ntin: Optional[str] = None
    category_1: Optional[str] = None
    category_2: Optional[str] = None
    category_3: Optional[str] = None
    brand: Optional[str] = None
    status: Optional[str] = None
    price_date: Optional[date] = None

    @field_validator("article", mode="before")
    @classmethod
    def clean_article(cls, v):
        if v is None:
            raise ValueError("article is required")
        s = str(v).strip()
        # Float-целые: 36008.0 → "36008"
        if re.match(r"^\d+\.0$", s):
            s = s[:-2]
        return s

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v):
        if not v:
            raise ValueError("name is required")
        import unicodedata, re as _re
        s = unicodedata.normalize("NFKC", str(v)).strip()
        s = _re.sub(r"\s+", " ", s)
        return s

    @field_validator("price_base", mode="before")
    @classmethod
    def clean_price(cls, v):
        if v is None:
            raise ValueError("price_base is required")
        if isinstance(v, (int, float)):
            return round(float(v), 2)
        s = str(v).strip().replace(" ", "").replace(",", ".")
        return round(float(s), 2)
