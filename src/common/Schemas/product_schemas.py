from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------- Product CRUD schemas ----------

class ProductBase(BaseModel):
    """Базовые поля товара."""
    brend: Optional[str] = Field(None, description="Бренд")
    articul: Optional[str] = Field(None, description="Артикул")
    name: str = Field(..., description="Название товара")
    quantity: Optional[str] = Field(None, description="Количество на складе")
    price: str = Field(..., description="Цена (строкой)")
    comment: Optional[str] = Field(None, description="Комментарий к товару")


class ProductCreate(ProductBase):
    """Создание товара (external_id опционален)."""
    external_id: Optional[str] = Field(None, description="Внешний ID")


class ProductUpdate(BaseModel):
    """Обновление товара — все поля необязательны."""
    brend: Optional[str] = None
    articul: Optional[str] = None
    name: Optional[str] = None
    quantity: Optional[str] = None
    price: Optional[str] = None
    comment: Optional[str] = None


class ProductResponse(ProductBase):
    """Ответ с полными данными товара."""
    id: int
    external_id: Optional[str] = None

    model_config = {"from_attributes": True}


# ---------- Order schemas ----------

class ItemOrder(BaseModel):
    """Позиция в заказе."""
    name: str = Field(..., description="Название товара")
    quantity: int = Field(1, ge=1, description="Количество")
    price: float = Field(..., ge=0, description="Цена за единицу (числом)")

    @field_validator("price", mode="before")
    @classmethod
    def _price_to_float(cls, v):
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(" ", "").replace(",", ".")
        return float(s)

class Order(BaseModel):
    """Данные для формирования заказа."""
    too_name: str = Field(..., description="Название ТОО")
    order_data: str = Field(..., description="Дата доставки")
    client_name: str = Field(..., description="Имя клиента")
    client_number: str = Field(..., description="Телефон клиента в формате +7XXXXXXXXXX")
    delivery_address: str = Field(..., description="Адрес доставки")
    payment: str = Field(..., description="Метод оплаты")
    items: List[ItemOrder] = Field(..., min_items=1, description="Список позиций")
    comment: str = Field(..., description="Комментарий Срочно/несрочно")