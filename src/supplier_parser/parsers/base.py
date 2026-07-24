"""Базовый класс парсера прайса."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.supplier_parser.models import SupplierProduct


class BaseParser(ABC):
    supplier_code: str = ""

    @abstractmethod
    def parse(self, file_path: str) -> List[SupplierProduct]:
        """Разобрать файл и вернуть нормализованные товары."""
        ...

    def _dedupe(self, items: List[SupplierProduct]) -> List[SupplierProduct]:
        """Дедупликация по article — берём последнюю запись."""
        seen = {}
        for item in items:
            seen[item.article] = item
        return list(seen.values())
