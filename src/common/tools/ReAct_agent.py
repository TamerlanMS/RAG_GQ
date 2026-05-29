from __future__ import annotations

import re
from typing import Annotated, Any, List, Optional, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from datetime import datetime, timezone as dt_timezone, timedelta

from src.common.llm_model import LLM
from src.common.Schemas.product_schemas import ItemOrder, Order
from src.common.vector_store import articul_store, is_articul, vector_store
from src.common.telegram_notifier import send_message_sync
from src.common.transliteration import get_search_variants
from src.db.CRUD import (
    find_product_by_articul,
    get_product_price,
    get_products_by_name,
    get_product_price_by_name,
    get_products_by_brand,
    get_brands_list,
)
from src.db.database import get_db
from src.settings.config import AGENT_PROMPT

load_dotenv()

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:
    ZoneInfo = None


@tool
def get_current_time(
    timezone: Optional[str] = "Asia/Qyzylorda",
    format: str = "iso",
    include_components: bool = True,
) -> dict:
    """
    Вернуть текущее время/дату.

    Аргументы:
      - timezone: IANA-таймзона (например, 'Asia/Qyzylorda'). Неверная -> UTC.
      - format: 'iso' | 'rfc3339' | 'unix' | 'custom'
      - include_components: добавить ли разложение по частям (date, time, year...).
    """
    tz = dt_timezone.utc
    tz_name = "UTC"
    if timezone and ZoneInfo is not None:
        try:
            tz = ZoneInfo(timezone)
            tz_name = timezone
        except Exception:
            tz = dt_timezone.utc
            tz_name = "UTC"

    now = datetime.now(tz)
    now_utc = now.astimezone(dt_timezone.utc)

    fmt = (format or "iso").lower()
    if fmt == "iso":
        result = now.isoformat()
    elif fmt == "rfc3339":
        s = now.isoformat()
        if now.utcoffset() == timedelta(0):
            s = now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        result = s
    elif fmt == "unix":
        result = int(now.timestamp())
    elif fmt == "custom":
        result = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        result = now.isoformat()

    out = {
        "result": result,
        "timezone": tz_name,
        "iso_utc": now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "unix": int(now.timestamp()),
    }

    if include_components:
        out["components"] = {
            "date": now.date().isoformat(),
            "time": now.time().replace(microsecond=0).isoformat(),
            "year": now.year,
            "month": now.month,
            "day": now.day,
            "hour": now.hour,
            "minute": now.minute,
            "second": now.second,
            "utc_offset": (
                ("+" if (now.utcoffset() or timedelta(0)) >= timedelta(0) else "-")
                + f"{abs(int((now.utcoffset() or timedelta(0)).total_seconds())) // 3600:02d}:"
                + f"{(abs(int((now.utcoffset() or timedelta(0)).total_seconds())) % 3600) // 60:02d}"
            ),
        }

    return out


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


@tool
def add(a: int, b: int) -> int:
    """Сложить два целых числа."""
    return a + b


@tool
def check_phone_number(phone_number: str) -> Optional[str]:
    """
    Приводит номер к формату +7XXXXXXXXXX.
    Возвращает нормализованный номер или None.
    """
    cleaned = re.sub(r"[^\d+]", "", phone_number)
    if cleaned.startswith("+7"):
        number = cleaned[2:]
    elif cleaned.startswith("8"):
        number = cleaned[1:]
    else:
        return None
    if len(number) == 10 and number.isdigit():
        return f"+7{number}"
    return None


@tool
def search_by_name(product_name: str) -> Any:
    """
    Поиск товара по НАИМЕНОВАНИЮ (русское описание, например: «кабель ВВГ 3х2.5»,
    «лоток перфорированный 200х50», «автоматический выключатель»).
    Сначала ищет в SQL по подстроке, затем в векторном индексе наименований.
    Возвращает список [{articul, name, brend, price, quantity}] с полными данными.
    """
    db_results = get_products_by_name(product_name)
    if db_results:
        return db_results
    return vector_store.search(product_name)  # тоже возвращает List[dict]


@tool
def search_by_articul(articul: str) -> Any:
    """
    Поиск товара по АРТИКУЛУ (буквенно-цифровой код, например: «PP24-1UC5ES-D05»,
    «A9D31620», «770073», «yabpvu-100-54»).
    Сначала точное совпадение в SQL, затем семантический поиск в индексе артикулов.
    Возвращает список [{articul, name, external_id, score}].
    """
    db = next(get_db())
    # Точное совпадение в SQL
    product = find_product_by_articul(db, articul)
    if product:
        return [{
            "articul": product.articul,
            "name": product.name,
            "external_id": product.external_id,
            "brend": product.brend,
            "price": product.price,
            "quantity": product.quantity,
        }]
    # Семантический поиск в векторном индексе артикулов
    return articul_store.search_articul(articul)


@tool
def smart_search(query: str) -> Any:
    """
    Умный поиск товара: АВТОМАТИЧЕСКИ определяет, является ли запрос артикулом
    или наименованием, и вызывает нужный индекс.
    При отсутствии результатов повторяет поиск с транслитерацией (кириллица ↔ латиница).

    Используй этот инструмент ПЕРВЫМ при любом запросе о товаре, если неизвестно
    что именно написал клиент — артикул или название.

    Примеры артикулов: PP24-1UC5ES-D05, A9D31620, 770073, yabpvu-100-54
    Примеры наименований: кабель ВВГ, лоток 200х50, дифавтомат 20А
    """
    variants = get_search_variants(query)

    if is_articul(query):
        db = next(get_db())
        for variant in variants:
            product = find_product_by_articul(db, variant)
            if product:
                return {
                    "matched_as": "articul_exact",
                    "results": [{
                        "articul": product.articul,
                        "name": product.name,
                        "external_id": product.external_id,
                        "brend": product.brend,
                        "price": product.price,
                        "quantity": product.quantity,
                    }]
                }
        vector_results = articul_store.search_articul(query)
        return {"matched_as": "articul_vector", "results": vector_results}
    else:
        for variant in variants:
            db_results = get_products_by_name(variant)
            if db_results:
                return {"matched_as": "name_sql", "results": db_results, "variant_used": variant}
        # Векторный поиск по всем вариантам, берём лучший результат
        for variant in variants:
            vector_results = vector_store.search(variant)
            if vector_results:
                return {"matched_as": "name_vector", "results": vector_results, "variant_used": variant}
        return {"matched_as": "not_found", "results": []}


@tool
def get_current_price(product_name: str):
    """
    Верни текущую цену товара по названию (поиск нечувствителен к регистру и неполному совпадению).
    Возвращает: {"id": ..., "name": "...", "brend": "...", "articul": "...",
                 "quantity": "...", "price": "...", "comment": "..."} или None.
    """
    db = next(get_db())
    return get_product_price_by_name(db, product_name)


@tool(parse_docstring=True, args_schema=Order)
def create_order(
    too_name: str,
    order_data: str,
    client_name: str,
    client_number: str,
    delivery_address: str,
    payment: str,
    items: List[ItemOrder],
    comment: str,
) -> str:
    """
    Сформировать текст заказа и отправить его в Telegram-группу.
    Требуются: Название ТОО, ФИО, Телефон, Адрес доставки, Дата доставки, Список позиций.
    """
    lines: List[str] = []
    counter = 1
    total_products = 0
    for it in items:
        price = int(round(float(it.price)))
        qty = int(it.quantity)
        line_sum = price * qty
        total_products += line_sum
        lines.append(
            f"№{counter}: {it.name}\n"
            f"Цена: {price} тг/шт.\n"
            f"Количество: {qty} шт.\n"
            f"Сумма: {line_sum} тг"
        )
        counter += 1

    lines_str = "\n".join(lines)
    comment = comment or "несрочно"
    delivery = "бесплатно" if total_products > 50000 else "платная"

    order_text = (
        "🛒 <b>Новый заказ</b>\n\n"
        f"<b>Название ТОО:</b> {too_name}\n"
        f"<b>ФИО:</b> {client_name}\n"
        f"<b>Телефон:</b> {client_number}\n"
        f"<b>Адрес доставки:</b> {delivery_address}\n"
        f"<b>Метод оплаты:</b> {payment}\n"
        f"<b>Дата доставки:</b> {order_data}\n\n"
        f"<b>Товары:</b>\n{lines_str}\n\n"
        f"<b>Итого к оплате:</b> {total_products} тг\n"
        f"<b>Доставка:</b> {delivery}\n"
        f"<b>Комментарий:</b> {comment}"
    )

    # Отправка в Telegram
    sent = send_message_sync(order_text)
    tg_status = "✅ Заказ отправлен менеджеру в Telegram." if sent else "⚠️ Не удалось отправить уведомление менеджеру."

    client_text = (
        "Ваш заказ:\n"
        f"Название ТОО: {too_name}\n"
        f"ФИО: {client_name}\n"
        f"Телефон: {client_number}\n"
        f"Адрес доставки: {delivery_address}\n"
        f"Метод оплаты: {payment}\n"
        f"Дата доставки: {order_data}\n"
        f"Товары:\n{lines_str}\n\n"
        f"Итого к оплате: {total_products} тг\n"
        f"Доставка: {delivery}\n"
        f"Комментарий: {comment}\n\n"
        f"{tg_status}\n"
        "❗Для подтверждения заказа обязательно нажмите на кнопку \"ОТПРАВИТЬ ЗАКАЗ\" после данного сообщения👇❗"
    )

    return client_text


@tool
def send_to_telegram(message: str) -> str:
    """
    Отправить произвольное сообщение в Telegram-группу менеджеров.
    Используй, когда нужно уведомить менеджеров о чём-либо помимо заказа.
    """
    sent = send_message_sync(message)
    if sent:
        return "Сообщение успешно отправлено в Telegram."
    return "Ошибка: не удалось отправить сообщение в Telegram."


@tool
def search_by_brand(brand: str, name_filter: str = "") -> Any:
    """
    Поиск товаров по БРЕНДУ/ПРОИЗВОДИТЕЛЮ.
    Используй когда клиент называет марку/фирму: «Lezard», «Сонекс», «IEK», «Schneider», «ABB», «EKF» и т.д.
    Опционально name_filter сужает поиск по ключевым словам в наименовании
    (например brand='Lezard', name_filter='светильник').
    Возвращает список [{articul, name, brend, price, quantity}] — до 20 позиций.
    """
    return get_products_by_brand(brand, name_filter or None)


@tool
def list_brands() -> Any:
    """
    Возвращает список всех брендов, представленных в базе.
    Используй когда клиент спрашивает «какие бренды есть?» или «какие производители?»
    """
    brands = get_brands_list()
    return brands


tools: List[BaseTool] = [
    add,
    smart_search,        # автодетект: артикул или наименование
    search_by_name,      # явный поиск по наименованию
    search_by_articul,   # явный поиск по артикулу
    search_by_brand,     # поиск по бренду/производителю
    list_brands,         # список всех брендов в базе
    get_current_price,
    check_phone_number,
    create_order,
    get_current_time,
    send_to_telegram,
]
tool_node = ToolNode(tools)
llm = LLM.bind_tools(tools)


def model_call(state: AgentState) -> AgentState:
    system_prompt = SystemMessage(content=AGENT_PROMPT)
    response = llm.invoke([system_prompt] + list(state["messages"]))
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "continue"
    return "end"


graph = StateGraph(AgentState)
graph.add_node("agent", model_call)
graph.add_node("tools", tool_node)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"continue": "tools", "end": END})
graph.add_edge("tools", "agent")

agent = graph.compile(checkpointer=InMemorySaver(), debug=True)
