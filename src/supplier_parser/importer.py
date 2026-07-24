"""
Importer — оркестратор загрузки прайса:
  detect → parse → diff → (confirm) → write to DB + price_history + import_log
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.common.logger import logger
from src.db.Models.supplier_models import (
    SupplierProduct as DBProduct,
    PriceHistory,
    ImportLog,
)
from src.supplier_parser.detector import detect_supplier
from src.supplier_parser.diff_engine import DiffReport, build_diff
from src.supplier_parser.models import SupplierProduct as ParsedProduct
from src.supplier_parser.registry import get_parser


# ─── Шаг 1: разбор файла ────────────────────────────────────

def parse_file(file_path: str, supplier_code: Optional[str] = None) -> dict:
    """
    Определяет поставщика, запускает парсер.
    Возвращает {supplier_code, items_count, sample (первые 5 строк)}.
    Исключение если поставщик не распознан.
    """
    code = supplier_code or detect_supplier(file_path)
    if not code:
        raise ValueError(
            f"Не удалось определить поставщика для файла '{os.path.basename(file_path)}'. "
            "Передайте supplier_code вручную."
        )
    parser = get_parser(code)
    if not parser:
        raise ValueError(f"Нет парсера для поставщика '{code}'")

    logger.info("Parsing %s as supplier=%s", os.path.basename(file_path), code)
    items = parser.parse(file_path)
    logger.info("Parsed %d items for %s", len(items), code)

    return {
        "supplier_code": code,
        "items": items,
        "items_count": len(items),
        "sample": [
            {"article": i.article, "name": i.name[:80], "price_base": i.price_base,
             "unit": i.unit, "brand": i.brand}
            for i in items[:5]
        ],
    }


# ─── Шаг 2: диффинг ─────────────────────────────────────────

def diff_file(db: Session, file_path: str, supplier_code: Optional[str] = None) -> dict:
    """
    Парсит файл и строит diff против текущей БД.
    Возвращает {supplier_code, summary, preview, _items (внутренний список)}.
    """
    result = parse_file(file_path, supplier_code)
    items: List[ParsedProduct] = result["items"]
    code = result["supplier_code"]

    report = build_diff(db, items, code)
    return {
        "supplier_code": code,
        "file_name": os.path.basename(file_path),
        "summary": report.summary(),
        "preview": report.preview(limit=10),
        "_report": report,
        "_items": items,
    }


# ─── Шаг 3: запись в БД ─────────────────────────────────────

def confirm_import(
    db: Session,
    diff_result: dict,
    mark_deleted: bool = False,
) -> ImportLog:
    """
    Применяет изменения из diff_result в БД транзакционно.
    mark_deleted=True → помечает удалённые позиции статусом 'удалён'.
    Сохраняет историю цен и import_log.
    """
    code: str = diff_result["supplier_code"]
    file_name: str = diff_result["file_name"]
    report: DiffReport = diff_result["_report"]
    items: List[ParsedProduct] = diff_result["_items"]

    log = ImportLog(
        file_name=file_name,
        supplier_code=code,
        rows_total=report.total,
        rows_new=len(report.items_new),
        rows_updated=len(report.items_updated),
        rows_deleted=len(report.items_deleted),
        rows_unchanged=len(report.items_unchanged),
        status="pending",
    )
    db.add(log)
    db.flush()

    try:
        # Записать историю цен для изменённых
        history_records = []
        for diff_item in report.items_updated:
            history_records.append(PriceHistory(
                supplier_code=code,
                article=diff_item.article,
                old_price=diff_item.old_price,
                new_price=diff_item.new_price,
            ))
        if history_records:
            db.add_all(history_records)

        # Upsert всех товаров из нового прайса
        BATCH = 500
        items_data = [
            {
                "supplier_code": i.supplier_code,
                "article": i.article,
                "name": i.name,
                "name_full": i.name_full,
                "unit": i.unit,
                "price_base": i.price_base,
                "price_with_vat": i.price_with_vat,
                "currency": i.currency,
                "vat_rate": i.vat_rate,
                "pack_qty": i.pack_qty,
                "ntin": i.ntin,
                "category_1": i.category_1,
                "category_2": i.category_2,
                "category_3": i.category_3,
                "brand": i.brand,
                "status": i.status,
                "price_date": i.price_date,
                "updated_at": datetime.utcnow(),
            }
            for i in items
        ]
        for start in range(0, len(items_data), BATCH):
            batch = items_data[start:start + BATCH]
            stmt = pg_insert(DBProduct).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_supplier_article",
                set_={
                    "name": stmt.excluded.name,
                    "name_full": stmt.excluded.name_full,
                    "unit": stmt.excluded.unit,
                    "price_base": stmt.excluded.price_base,
                    "price_with_vat": stmt.excluded.price_with_vat,
                    "pack_qty": stmt.excluded.pack_qty,
                    "ntin": stmt.excluded.ntin,
                    "category_1": stmt.excluded.category_1,
                    "category_2": stmt.excluded.category_2,
                    "category_3": stmt.excluded.category_3,
                    "brand": stmt.excluded.brand,
                    "status": stmt.excluded.status,
                    "price_date": stmt.excluded.price_date,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            db.execute(stmt)

        # Удалённые позиции — пометить статусом "удалён"
        if mark_deleted:
            from sqlalchemy import update
            deleted_articles = [d.article for d in report.items_deleted]
            if deleted_articles:
                db.execute(
                    update(DBProduct)
                    .where(DBProduct.supplier_code == code)
                    .where(DBProduct.article.in_(deleted_articles))
                    .values(status="удалён", updated_at=datetime.utcnow())
                )

        log.status = "confirmed"
        db.commit()
        logger.info(
            "Import confirmed: supplier=%s new=%d updated=%d deleted=%d",
            code, log.rows_new, log.rows_updated, log.rows_deleted,
        )
    except Exception as e:
        db.rollback()
        log.status = "error"
        log.error_message = str(e)
        db.add(log)
        db.commit()
        logger.error("Import failed for %s: %s", code, e, exc_info=True)
        raise

    return log
