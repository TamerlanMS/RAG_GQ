from __future__ import annotations
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple, Annotated

import re
import requests  # type: ignore
from fastapi import Depends
from sqlalchemy import select, update, or_, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.common.logger import logger
from src.common.vector_store import articul_store, vector_store
from src.db.database import Base, SessionLocal, engine, get_db
from src.db.Models.product_models import Product

# ---------- служебные операции ----------

def cleanup_db_spaces() -> int:
    """
    Обрезает пробелы в начале и конце строк во всех строковых полях таблицы products.
    Возвращает количество обновлённых строк.
    """
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE products SET
                name        = TRIM(name),
                brend       = TRIM(brend),
                articul     = TRIM(articul),
                external_id = TRIM(external_id),
                quantity    = TRIM(quantity),
                price       = TRIM(price),
                comment     = TRIM(comment)
            WHERE
                name        IS DISTINCT FROM TRIM(name)   OR
                brend       IS DISTINCT FROM TRIM(brend)  OR
                articul     IS DISTINCT FROM TRIM(articul) OR
                external_id IS DISTINCT FROM TRIM(external_id) OR
                quantity    IS DISTINCT FROM TRIM(quantity) OR
                price       IS DISTINCT FROM TRIM(price)  OR
                comment     IS DISTINCT FROM TRIM(comment)
        """))
        db.commit()
        count = result.rowcount
        logger.info("cleanup_db_spaces: trimmed %d rows", count)
        return count
    except Exception as e:
        db.rollback()
        logger.error("cleanup_db_spaces error: %s", e, exc_info=True)
        raise
    finally:
        db.close()


def create_db() -> str:
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exp:
        if "already exists" in str(exp):
            logger.info("Database already exists")
            return "Database already exists"
        raise
    else:
        return "Database created successfully"


def drop_db() -> str:
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception as exp:
        if "does not exist" in str(exp):
            logger.info("Database does not exist")
            return "Database does not exist"
        raise
    else:
        return "Database dropped successfully"


# ---------- загрузка/парсинг JSON ----------

def __get_json_from_url(
    address: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, Any]] = None,
) -> Any:
    resp = requests.get(address, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def __extract_products_array(json_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not json_data or "Products" not in json_data:
        raise ValueError("Expected JSON object with key 'Products'")
    products = json_data["Products"]
    if not isinstance(products, list):
        raise ValueError("'Products' must be an array")
    return products


_NONE_STRINGS = {"none", "null", "н/д", "-", ""}

def _clean(value: Any) -> Optional[str]:
    """
    None / 'None' / 'null' / пустая строка → None, иначе stripped string.
    float-целые (17776.0, 770073.0) → '17776', '770073' (без .0, нули сохраняются).
    """
    if value is None:
        return None
    # float без дробной части → целое, чтобы не получать "17776.0" или "770073.0"
    if isinstance(value, float) and value == int(value):
        value = int(value)
    s = str(value).strip()
    if s.lower() in _NONE_STRINGS:
        return None
    return s


def __parse_flat_products(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Optional[str]]]:
    """
    Возвращает список словарей с полями:
      external_id, brend, articul, name, quantity, price, comment
    Все пустые/"None"/"null" значения приводятся к None (SQL NULL).
    """
    out: List[Dict[str, Optional[str]]] = []
    for it in products:
        if not isinstance(it, dict):
            continue
        name = _clean(it.get("name"))
        price = _clean(it.get("price"))
        if not name or not price:
            continue
        out.append({
            "external_id": _clean(it.get("id")),
            "brend":       _clean(it.get("brend")),
            "articul":     _clean(it.get("articul")),
            "name":        name,
            "quantity":    _clean(it.get("quantity")),
            "price":       price,
            "comment":     _clean(it.get("comment")),
        })
    if not out:
        raise ValueError("No valid items in 'Products'")
    return out


# ---------- публичный импорт ----------

def update_db(
    db: Annotated[Session, Depends(get_db)],
    json_url: str = "",
    json_data: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Ожидает формат:
    {
      "Date": "...",
      "Products": [
        { "id": "...", "brend": "...", "articul": "...", "name": "...",
          "quantity": "...", "price": "...", "comment": "..." },
        ...
      ]
    }
    Upsert по external_id (если есть), иначе по name.
    """
    data = json_data if json_data is not None else __get_json_from_url(json_url)
    items = __parse_flat_products(__extract_products_array(data))

    # Дедупликация по name внутри самого импорта (берём последнюю запись)
    deduped: Dict[str, Dict] = {}
    for item in items:
        deduped[item["name"]] = item
    items = list(deduped.values())

    # PostgreSQL INSERT ... ON CONFLICT (name) DO UPDATE SET ...
    # Атомарный upsert — никаких UniqueViolation независимо от состояния БД.
    BATCH = 500
    total = 0
    for i in range(0, len(items), BATCH):
        batch = items[i : i + BATCH]
        stmt = pg_insert(Product).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={
                "external_id": stmt.excluded.external_id,
                "brend":       stmt.excluded.brend,
                "articul":     stmt.excluded.articul,
                "quantity":    stmt.excluded.quantity,
                "price":       stmt.excluded.price,
                "comment":     stmt.excluded.comment,
            },
        )
        db.execute(stmt)
        db.commit()
        total += len(batch)
        logger.info("update_db: upserted batch %d/%d", i + len(batch), len(items))
    logger.info("update_db: total upserted=%s", total)

    # Очистка пробелов
    try:
        trimmed = cleanup_db_spaces()
        logger.info("update_db: trimmed spaces in %d rows", trimmed)
    except Exception as e:
        logger.warning("update_db: cleanup_db_spaces failed: %s", e)

    # Пересборка индекса наименований (обогащённые данные: имя + бренд + артикул)
    try:
        products_all = get_all_products()
        msg = vector_store.rebuild_vector_store(products=products_all)
        logger.info("Names vector store rebuilt: %s", msg)
    except Exception as e:
        logger.warning("Names vector store rebuild failed: %s", e)

    # Пересборка индекса артикулов
    try:
        pairs = get_all_articuls()
        if pairs:
            msg2 = articul_store.rebuild_articuls(pairs)
            logger.info("Articul vector store rebuilt: %s", msg2)
    except Exception as e:
        logger.warning("Articul vector store rebuild failed: %s", e)

    return total


# ---------- CRUD одиночных записей ----------

def create_product(db: Session, data: Dict[str, Any]) -> Product:
    product = Product(
        external_id=data.get("external_id"),
        brend=data.get("brend"),
        articul=data.get("articul"),
        name=data["name"],
        quantity=data.get("quantity"),
        price=data["price"],
        comment=data.get("comment"),
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def get_product_by_id(db: Session, product_id: int) -> Optional[Product]:
    return db.scalar(select(Product).where(Product.id == product_id))


def update_product(db: Session, product_id: int, data: Dict[str, Any]) -> Optional[Product]:
    product = get_product_by_id(db, product_id)
    if not product:
        return None
    for field, value in data.items():
        if value is not None:
            setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product_id: int) -> bool:
    product = get_product_by_id(db, product_id)
    if not product:
        return False
    db.delete(product)
    db.commit()
    return True


def list_products(db: Session, skip: int = 0, limit: int = 100) -> List[Product]:
    return list(db.scalars(select(Product).offset(skip).limit(limit)).all())


# ---------- утилиты поиска ----------
MIN_TOKEN_LEN = 3


def _tokenize(q: str) -> List[str]:
    return [t for t in re.split(r"[^\wА-Яа-яЁё]+", q.lower()) if len(t) >= MIN_TOKEN_LEN]


def _best_match(query: str, candidates: List[Product]) -> Optional[Product]:
    if not candidates:
        return None
    scored = [(SequenceMatcher(None, query.lower(), p.name.lower()).ratio(), p) for p in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def find_product_best(db: Session, query: str) -> Optional[Product]:
    p = db.scalar(select(Product).where(Product.name.ilike(f"%{query}%")))
    if p:
        return p
    tokens = _tokenize(query)
    if tokens:
        q = select(Product)
        for t in tokens:
            q = q.where(Product.name.ilike(f"%{t}%"))
        hits = db.scalars(q).all()
        if hits:
            return _best_match(query, hits)
        hits = db.scalars(
            select(Product).where(or_(*[Product.name.ilike(f"%{t}%") for t in tokens]))
        ).all()
        if hits:
            return _best_match(query, hits)
    return None


def _rows_to_dicts(rows) -> List[dict]:
    return [
        {
            "articul": r.articul,
            "name": r.name,
            "brend": r.brend,
            "price": r.price,
            "quantity": r.quantity,
            "comment": r.comment,
        }
        for r in rows
    ]


def get_products_by_name(product_name: str, limit: int = 15) -> List[dict]:
    """
    Трёхуровневый поиск по наименованию. Возвращает полные карточки.

    Стратегия 1 — ILIKE всей фразой: 'кабель ВВГ 3х2.5' → ищет подстроку целиком.
    Стратегия 2 — AND по токенам: каждое слово должно присутствовать в названии.
    Стратегия 3 — OR по токенам: хоть одно слово совпадает, сортировка по числу совпадений.
    """
    db = next(get_db())

    # Стратегия 1: полная подстрока
    rows = db.scalars(
        select(Product).where(Product.name.ilike(f"%{product_name}%")).limit(limit)
    ).all()
    if rows:
        return _rows_to_dicts(rows)

    # Токенизация для стратегий 2 и 3
    tokens = _tokenize(product_name)
    if not tokens:
        return []

    # Стратегия 2: все токены присутствуют (AND)
    q = select(Product)
    for t in tokens:
        q = q.where(Product.name.ilike(f"%{t}%"))
    rows = db.scalars(q.limit(limit)).all()
    if rows:
        return _rows_to_dicts(rows)

    # Стратегия 3: хотя бы один токен (OR), сортировка по числу совпадений
    rows = db.scalars(
        select(Product)
        .where(or_(*[Product.name.ilike(f"%{t}%") for t in tokens]))
        .limit(limit * 3)
    ).all()
    if rows:
        scored = sorted(
            rows,
            key=lambda r: sum(1 for t in tokens if t in r.name.lower()),
            reverse=True,
        )
        return _rows_to_dicts(scored[:limit])

    return []


def get_product_price_by_name(db: Session, product_name: str) -> Optional[dict]:
    p = find_product_best(db, product_name)
    if not p:
        return None
    return {
        "id": p.id,
        "external_id": p.external_id,
        "brend": p.brend,
        "articul": p.articul,
        "name": p.name,
        "quantity": p.quantity,
        "price": p.price,
        "comment": p.comment,
    }


def get_product_price(product_name: str) -> Optional[str]:
    db = next(get_db())
    row = db.execute(select(Product.price).where(Product.name == product_name)).first()
    return row[0] if row else None


def get_all_products() -> List[dict]:
    """Возвращает все товары как словари для пересборки векторного индекса."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(Product)).all()
        return [
            {
                "name": r.name,
                "brend": r.brend or "",
                "articul": r.articul or "",
                "price": r.price or "",
                "quantity": r.quantity or "",
            }
            for r in rows
        ]
    finally:
        db.close()


def get_all_articuls() -> List[dict]:
    """Возвращает [{articul, name, external_id}] для всех товаров с артикулом."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Product.articul, Product.name, Product.external_id)
            .where(Product.articul.isnot(None))
        ).all()
        return [
            {"articul": r.articul, "name": r.name, "external_id": r.external_id or ""}
            for r in rows
        ]
    finally:
        db.close()


def find_product_by_articul(db: Session, articul: str) -> Optional[Product]:
    """Точный поиск по артикулу (регистронезависимый)."""
    return db.scalar(
        select(Product).where(Product.articul.ilike(articul))
    )


def get_products_by_brand(
    brand: str,
    name_filter: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Поиск товаров по бренду (регистронезависимый, подстрока).
    Опционально фильтрует по подстроке в наименовании.
    Возвращает список {articul, name, brend, price, quantity}.
    """
    db = SessionLocal()
    try:
        q = select(Product).where(Product.brend.ilike(f"%{brand}%"))
        if name_filter:
            for token in _tokenize(name_filter):
                q = q.where(Product.name.ilike(f"%{token}%"))
        rows = db.scalars(q.limit(limit)).all()
        return [
            {
                "articul": r.articul,
                "name": r.name,
                "brend": r.brend,
                "price": r.price,
                "quantity": r.quantity,
                "comment": r.comment,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_brands_list() -> List[str]:
    """Возвращает отсортированный список уникальных брендов из БД."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Product.brend)
            .where(Product.brend.isnot(None))
            .distinct()
            .order_by(Product.brend)
        ).all()
        return [r[0] for r in rows]
    finally:
        db.close()
