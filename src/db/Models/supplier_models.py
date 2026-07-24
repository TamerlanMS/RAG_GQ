"""
SQLAlchemy-модели для системы парсинга прайсов поставщиков.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db.database import Base


class Supplier(Base):
    """Справочник поставщиков."""
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)   # himel, iek, dkc ...
    name = Column(String(200), nullable=False)
    contact = Column(String(200))
    update_frequency = Column(String(50))                    # monthly, weekly ...
    created_at = Column(DateTime, server_default=func.now())


class SupplierProduct(Base):
    """
    Нормализованный каталог товаров от поставщиков.
    Уникальность: (supplier_code, article).
    """
    __tablename__ = "supplier_catalog"
    __table_args__ = (
        UniqueConstraint("supplier_code", "article", name="uq_supplier_article"),
    )

    id = Column(BigInteger, primary_key=True)
    supplier_code = Column(String(50), nullable=False, index=True)
    article = Column(String(100), nullable=False, index=True)

    name = Column(Text, nullable=False)
    name_full = Column(Text)

    unit = Column(String(20), nullable=False, default="шт")
    price_base = Column(Numeric(14, 2), nullable=False)      # без НДС
    price_with_vat = Column(Numeric(14, 2))                  # с НДС
    currency = Column(String(3), nullable=False, default="KZT")
    vat_rate = Column(Numeric(5, 2), nullable=False, default=12)

    pack_qty = Column(Integer)
    ntin = Column(String(30))

    category_1 = Column(String(200))
    category_2 = Column(String(200))
    category_3 = Column(String(200))
    brand = Column(String(100))

    status = Column(String(50))       # в наличии / под заказ / удалён
    price_date = Column(Date)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PriceHistory(Base):
    """История изменений цен."""
    __tablename__ = "price_history"

    id = Column(BigInteger, primary_key=True)
    supplier_code = Column(String(50), nullable=False, index=True)
    article = Column(String(100), nullable=False, index=True)
    old_price = Column(Numeric(14, 2))
    new_price = Column(Numeric(14, 2), nullable=False)
    changed_at = Column(DateTime, server_default=func.now())


class ImportLog(Base):
    """Лог каждой загрузки прайса."""
    __tablename__ = "import_log"

    id = Column(Integer, primary_key=True)
    file_name = Column(String(500), nullable=False)
    supplier_code = Column(String(50), nullable=False)
    rows_total = Column(Integer, default=0)
    rows_new = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    rows_deleted = Column(Integer, default=0)
    rows_unchanged = Column(Integer, default=0)
    status = Column(String(50), default="pending")   # pending/confirmed/error
    error_message = Column(Text)
    imported_at = Column(DateTime, server_default=func.now())


class SupplierMapping(Base):
    """
    Кэш маппингов Claude API для неизвестных поставщиков.
    При повторной загрузке ИИ не вызывается.
    """
    __tablename__ = "supplier_mappings"

    id = Column(Integer, primary_key=True)
    supplier_code = Column(String(50), nullable=False)
    file_signature = Column(String(200), nullable=False)     # sha256 первых 1000 байт
    mapping_json = Column(JSONB, nullable=False)
    confirmed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
