from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Path, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette import status
from starlette.requests import Request

from src.common.logger import logger
from src.common.Schemas.product_schemas import ProductCreate, ProductResponse, ProductUpdate
from src.common.tools.ReAct_agent import agent
from src.supplier_parser.importer import parse_file, diff_file, confirm_import
from src.supplier_parser.registry import list_suppliers
from src.db.Models.supplier_models import ImportLog
from src.db.CRUD import (
    create_db,
    create_product,
    delete_product,
    get_product_by_id,
    list_products,
    update_db,
    update_product,
    cleanup_db_spaces,
    drop_db,
)
from src.db.database import get_db

router: APIRouter = APIRouter()
logger.info("Starting app .....")


# ─────────────────────────── Agent ─────────────────────────── #

class AskRequest(BaseModel):
    user_input: str = Field(..., description="Сообщение пользователя")
    thread_id: str = Field(..., description="Номер телефона клиента (+7XXXXXXXXXX) — ключ истории диалога")


@router.post("/ask", tags=["Agent"])
async def ask_agent(body: AskRequest) -> Any:
    """
    Отправить сообщение агенту.
    История диалога хранится по номеру телефона (thread_id).
    """
    try:
        inputs = {"messages": [("user", body.user_input)]}
        config = {
            "configurable": {"thread_id": body.thread_id},
            "recursion_limit": 100,
        }
    except Exception as e:
        logger.error("Unexpected error building request - %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {e}",
        )

    try:
        answer = agent.invoke(inputs, config=config)
        ai_answer = answer["messages"][-1].content
    except AttributeError:
        logger.warning("Unexpected response format from agent", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected response format from agent",
        )
    except Exception as e:
        logger.error("Unexpected error from LLM - %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )

    return {"answer": ai_answer}


# ─────────────────────────── DB utils ─────────────────────────── #

@router.get("/status_DB", tags=["database"])
async def get_postgres_db_status(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Health-check: версия Postgres."""
    try:
        version = db.scalar(text("SELECT version();"))
        return {"status": status.HTTP_200_OK, "DB_version": version}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error connecting to DB: {e}",
        )


@router.post("/create_DB", tags=["database"])
async def create_tables() -> Dict[str, Any]:
    """Создаёт таблицы при необходимости."""
    try:
        message = create_db()
        return {"status_code": status.HTTP_200_OK, "transaction": message}
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Error creating tables"
        )


@router.post("/update_DB", tags=["database"])
async def update_products(
    payload: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Массовый upsert товаров.

    Пустой POST → тянет JSON с дефолтного URL.
    С телом → ожидает:
    ```json
    {
      "Date": "2025-09-09T10:14:58Z",
      "Products": [
        { "id": "00-114", "brend": "...", "articul": "...",
          "name": "...", "quantity": "10", "price": "1500", "comment": "..." }
      ]
    }
    ```
    """
    try:
        if payload is not None and "Products" not in payload:
            raise ValueError("Expected JSON object with key 'Products'")
        total = update_db(db, json_data=payload) if payload is not None else update_db(db)
        return {
            "status_code": status.HTTP_202_ACCEPTED,
            "message": f"Total updated: {total}",
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {e}",
        )

@router.delete("/drop_DB", tags=["delete DB"])
async def delete_db() -> Dict[str, Any]:
    message = drop_db()
    return {"status_code": 201, "message": f"{message}"}

@router.post("/cleanup_spaces", tags=["database"])
async def cleanup_spaces() -> Dict[str, Any]:
    """Обрезает пробелы в начале/конце строк во всех полях таблицы products."""
    try:
        trimmed = cleanup_db_spaces()
        return {"status": "ok", "rows_updated": trimmed}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {e}",
        )


# ─────────────────────────── Products CRUD ─────────────────────────── #

@router.get("/products", response_model=List[ProductResponse], tags=["products"])
async def get_products(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Список товаров с пагинацией."""
    return list_products(db, skip=skip, limit=limit)


@router.get("/products/{product_id}", response_model=ProductResponse, tags=["products"])
async def get_product(
    product_id: int = Path(..., description="ID товара"),
    db: Session = Depends(get_db),
):
    """Получить товар по ID."""
    product = get_product_by_id(db, product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, tags=["products"])
async def create_product_endpoint(
    body: ProductCreate,
    db: Session = Depends(get_db),
):
    """Создать новый товар."""
    try:
        return create_product(db, body.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not create product: {e}",
        )


@router.patch("/products/{product_id}", response_model=ProductResponse, tags=["products"])
async def update_product_endpoint(
    product_id: int = Path(..., description="ID товара"),
    body: ProductUpdate = Body(...),
    db: Session = Depends(get_db),
):
    """Обновить поля товара (частичное обновление)."""
    product = update_product(db, product_id, body.model_dump(exclude_none=True))
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["products"])
async def delete_product_endpoint(
    product_id: int = Path(..., description="ID товара"),
    db: Session = Depends(get_db),
):
    """Удалить товар по ID."""
    deleted = delete_product(db, product_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


# ─────────────────────────── Supplier Price Import ─────────────────────────── #

import tempfile, os as _os

class ConfirmImportRequest(BaseModel):
    supplier_code: str
    file_name: str
    mark_deleted: bool = False


# Временное хранилище diff_result между шагами (в памяти, per-process)
# В продакшене заменить на Redis или таблицу import_sessions
_pending_imports: Dict[str, Any] = {}


@router.get("/suppliers", tags=["suppliers"])
async def get_suppliers():
    """Список поставщиков с зарегистрированными парсерами."""
    return {"suppliers": list_suppliers()}


@router.post("/suppliers/upload", tags=["suppliers"])
async def upload_supplier_price(
    file: UploadFile = File(...),
    supplier_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Загрузить прайс-лист поставщика (.xlsx).
    1. Автоопределение поставщика (или передать supplier_code вручную).
    2. Парсинг файла.
    3. Diff против текущей БД.
    4. Возврат summary + preview первых 10 строк каждой категории.
    Для применения изменений вызвать POST /suppliers/confirm.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Поддерживаются только .xlsx/.xls файлы")

    # Сохраняем во временный файл
    suffix = ".xlsx" if file.filename.endswith(".xlsx") else ".xls"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = diff_file(db, tmp_path, supplier_code)
        # Сохраняем для шага confirm
        session_key = f"{result['supplier_code']}:{result['file_name']}"
        _pending_imports[session_key] = result
        return {
            "status": "preview_ready",
            "session_key": session_key,
            "supplier_code": result["supplier_code"],
            "file_name": result["file_name"],
            "summary": result["summary"],
            "preview": result["preview"],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("upload_supplier_price error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _os.unlink(tmp_path)


@router.post("/suppliers/confirm", tags=["suppliers"])
async def confirm_supplier_import(
    body: ConfirmImportRequest,
    db: Session = Depends(get_db),
):
    """
    Подтвердить загрузку прайса после просмотра preview.
    Применяет изменения в БД, сохраняет историю цен, пишет import_log.
    """
    session_key = f"{body.supplier_code}:{body.file_name}"
    diff_result = _pending_imports.get(session_key)
    if not diff_result:
        raise HTTPException(
            status_code=404,
            detail=f"Нет ожидающего импорта для '{session_key}'. Сначала вызовите /suppliers/upload.",
        )
    try:
        log = confirm_import(db, diff_result, mark_deleted=body.mark_deleted)
        _pending_imports.pop(session_key, None)
        return {
            "status": "confirmed",
            "supplier_code": log.supplier_code,
            "rows_new": log.rows_new,
            "rows_updated": log.rows_updated,
            "rows_deleted": log.rows_deleted,
            "rows_unchanged": log.rows_unchanged,
            "import_id": log.id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suppliers/import_log", tags=["suppliers"])
async def get_import_log(
    supplier_code: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """История загрузок прайсов."""
    from sqlalchemy import select, desc
    q = select(ImportLog).order_by(desc(ImportLog.imported_at)).limit(limit)
    if supplier_code:
        q = q.where(ImportLog.supplier_code == supplier_code)
    rows = db.scalars(q).all()
    return [
        {
            "id": r.id,
            "supplier_code": r.supplier_code,
            "file_name": r.file_name,
            "rows_new": r.rows_new,
            "rows_updated": r.rows_updated,
            "rows_deleted": r.rows_deleted,
            "status": r.status,
            "imported_at": r.imported_at.isoformat() if r.imported_at else None,
        }
        for r in rows
    ]
