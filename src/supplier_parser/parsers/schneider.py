"""
Парсер прайса Schneider Electric (файл «Price-list KZ...»).

Структура листа «Тариф 2026»:
  Строки 1-5: матрица скидок по коллекциям
    row1: заголовок (Коллекция, Ваша скидка, Итог)
    row2: Розничная, <скидка>
    row3: Промышленная, <скидка>
    row4: Проектная, <скидка>
    row5: Проектная Smart, <скидка>
  Строка 7: заголовок данных
  Строка 8+: товары

Колонки (0-based):
  0  A  Артикул (числовой, например 296691)
  1  B  Описание = name
  2  C  Тариф с НДС = price_with_vat
  3  D  Тариф с НДС с учётом скидки
  4  E  Ед.изм.
  5  F  Коллекция (Розничная / Промышленная / Проектная)
  6  G  Складской статус
  8  H  Уровень иерархии 1 = category_1
  9  I  Уровень иерархии 2 = category_2
  10 J  Уровень иерархии 3 = category_3
"""
from __future__ import annotations

from typing import Dict, List

import openpyxl

from src.supplier_parser.models import SupplierProduct
from src.supplier_parser.normalizer import (
    clean_str, clean_price, clean_unit, price_excl_vat,
)
from src.supplier_parser.parsers.base import BaseParser

_SHEET_MAIN = "Тариф 2026"
_SHEET_REMOVED = "Выводятся из ассортимента"
_HEADER_ROW = 7
_DATA_FROM = 8
_DISCOUNT_ROWS = range(2, 6)   # строки 2-5 содержат скидки


class SchneiderParser(BaseParser):
    supplier_code = "schneider"

    def parse(self, file_path: str) -> List[SupplierProduct]:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        # Читаем матрицу скидок (строки 1-5)
        discounts: Dict[str, float] = {}
        ws = wb[_SHEET_MAIN]
        for row in ws.iter_rows(min_row=2, max_row=5, values_only=True):
            col = clean_str(row[0])
            disc = row[1]
            if col and isinstance(disc, (int, float)):
                discounts[col.strip()] = float(disc)

        items: List[SupplierProduct] = []
        price_date = None

        for row in ws.iter_rows(min_row=_DATA_FROM, values_only=True):
            article = clean_str(row[0])
            name = clean_str(row[1])
            if not article or not name:
                continue
            price_with_vat = clean_price(row[2])
            if price_with_vat is None:
                continue
            # Цена с учётом скидки (col3) — используем как price_base (без НДС)
            price_discounted = clean_price(row[3])
            base_price_vat = price_discounted if price_discounted else price_with_vat
            price_base = price_excl_vat(base_price_vat)
            try:
                items.append(SupplierProduct(
                    supplier_code=self.supplier_code,
                    article=article,
                    name=name,
                    unit=clean_unit(row[4]) if len(row) > 4 else "шт",
                    price_base=price_base,
                    price_with_vat=price_with_vat,
                    category_1=clean_str(row[8]) if len(row) > 8 else None,
                    category_2=clean_str(row[9]) if len(row) > 9 else None,
                    category_3=clean_str(row[10]) if len(row) > 10 else None,
                    brand="Schneider Electric",
                    status=clean_str(row[6]) if len(row) > 6 else None,
                    price_date=price_date,
                ))
            except Exception:
                continue

        # Удалённые позиции — статус "удалён"
        if _SHEET_REMOVED in wb.sheetnames:
            ws_del = wb[_SHEET_REMOVED]
            for row in ws_del.iter_rows(min_row=_DATA_FROM, values_only=True):
                article = clean_str(row[0])
                name = clean_str(row[1])
                if not article or not name:
                    continue
                price_with_vat = clean_price(row[2])
                if price_with_vat is None:
                    continue
                try:
                    items.append(SupplierProduct(
                        supplier_code=self.supplier_code,
                        article=article,
                        name=name,
                        unit=clean_unit(row[4]) if len(row) > 4 else "шт",
                        price_base=price_excl_vat(price_with_vat),
                        price_with_vat=price_with_vat,
                        brand="Schneider Electric",
                        status="удалён",
                        price_date=price_date,
                    ))
                except Exception:
                    continue

        wb.close()
        return self._dedupe(items)
