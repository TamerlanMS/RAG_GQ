"""
Конвертация XLS-выгрузки из 1С → products_import.json для /api/v1/update_DB.

Использование:
    python scripts/xls_to_import.py <путь_к_файлу.xls> [output.json]

Формат XLS (выгрузка «Ведомость по партиям товаров»):
    Строка 7 — заголовки: Код | Номенклатура | Артикул | Бренд | Количество | Себестоимость | Комментарий
    Строки 8+ — данные

Особенности:
  - Числа из Excel хранятся как float (17776.0) → конвертируем в int-строку ("17776")
  - Артикулы с ведущими нулями: если в названии стоит "00304 TMC...", а Excel дал артикул=304,
    восстанавливаем "00304" из названия
  - Себестоимость используется как цена (price)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import xlrd
except ImportError:
    print("Установите xlrd: pip install xlrd")
    sys.exit(1)


HEADER_MARKERS = ("Код", "Номенклатура")

COL_MAP = {
    "id":       "Код",
    "name":     "Номенклатура",
    "articul":  "Артикул",
    "brend":    "Бренд (св-во Номенклатура)",
    "quantity": "Количество",
    "price":    "Себестоимость (ед.товара)",
    "comment":  "Комментарий",
}

_NONE_VALS = {"none", "null", "н/д", "-", ""}


def cell_to_str(cell) -> str:
    """Ячейка → строка. Float-целые без .0, ведущие нули сохраняются."""
    if cell.ctype == 0:   # empty
        return ""
    if cell.ctype == 1:   # text
        return str(cell.value).strip()
    if cell.ctype == 2:   # number
        v = cell.value
        if v == int(v):
            return str(int(v))   # 17776.0 → "17776"
        return str(v)
    return str(cell.value).strip()


def clean(s: str) -> str | None:
    return s.strip() if s.strip().lower() not in _NONE_VALS else None


def format_id(raw: str, width: int) -> str:
    """Числовой ID → строка с ведущими нулями до фиксированной ширины."""
    if raw.isdigit():
        return raw.zfill(width)
    return raw


def restore_leading_zeros(name: str, articul: str) -> str:
    """
    Если артикул — чистое число (Excel потерял ведущие нули),
    но название начинается с нуля + то же число, берём вариант из названия.
    Пример: articul='304', name='00304 TMC...' → '00304'
    """
    if not articul or not articul.isdigit():
        return articul
    m = re.match(r"^(0+" + re.escape(articul) + r")\b", name.strip())
    return m.group(1) if m else articul


def find_header_row(ws) -> int | None:
    for r in range(ws.nrows):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        if all(m in row for m in HEADER_MARKERS):
            return r
    return None


def build_col_index(ws, header_row: int) -> dict[str, int]:
    headers = [str(ws.cell_value(header_row, c)).strip() for c in range(ws.ncols)]
    index: dict[str, int] = {}
    for key, header in COL_MAP.items():
        # Поиск без учёта хвостовых пробелов (в файле бывает "Артикул ")
        for i, h in enumerate(headers):
            if h.strip() == header.strip():
                index[key] = i
                break
    return index


def convert(xls_path: str, output_path: str) -> int:
    wb = xlrd.open_workbook(xls_path)
    ws = wb.sheet_by_index(0)

    header_row = find_header_row(ws)
    if header_row is None:
        raise ValueError("Не найдена строка с заголовками (Код, Номенклатура)")

    col = build_col_index(ws, header_row)
    missing = [k for k in ("id", "name", "price") if k not in col]
    if missing:
        raise ValueError(f"Не найдены обязательные колонки: {missing}")

    # Ширина паддинга ID = длина максимального числового ID в файле
    id_col = col.get("id")
    id_width = 1
    if id_col is not None:
        max_id = max(
            (int(ws.cell(r, id_col).value)
             for r in range(header_row + 1, ws.nrows)
             if ws.cell(r, id_col).ctype == 2 and ws.cell(r, id_col).value),
            default=1,
        )
        id_width = len(str(int(max_id)))

    products = []
    for r in range(header_row + 1, ws.nrows):
        name = cell_to_str(ws.cell(r, col["name"])).strip() if "name" in col else ""
        price = cell_to_str(ws.cell(r, col["price"])) if "price" in col else ""

        if not clean(name) or not clean(price):
            continue
        if name.lower() in ("итог", "итого"):
            continue

        raw_art = cell_to_str(ws.cell(r, col["articul"])) if "articul" in col else ""
        articul = restore_leading_zeros(name, raw_art)
        raw_id = cell_to_str(ws.cell(r, id_col)) if id_col is not None else ""

        products.append({
            "id":       format_id(raw_id, id_width),
            "name":     name,
            "articul":  articul,
            "brend":    cell_to_str(ws.cell(r, col["brend"])) if "brend" in col else "",
            "quantity": cell_to_str(ws.cell(r, col["quantity"])) if "quantity" in col else "",
            "price":    price,
            "comment":  cell_to_str(ws.cell(r, col["comment"])) if "comment" in col else "",
        })

    result = {
        "Date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Products": products,
    }
    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(products)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    xls_file = sys.argv[1]
    out_file = sys.argv[2] if len(sys.argv) > 2 else "products_import.json"

    try:
        n = convert(xls_file, out_file)
        print(f"✅ Конвертировано {n} товаров → {out_file}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
