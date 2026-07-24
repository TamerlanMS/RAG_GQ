"""
DiffEngine — сравнивает новый прайс с текущим состоянием БД.
Возвращает DiffReport: новые / изменённые / удалённые / без изменений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from src.db.Models.supplier_models import SupplierProduct as DBProduct
from src.supplier_parser.models import SupplierProduct as ParsedProduct


@dataclass
class DiffItem:
    article: str
    name: str
    old_price: Optional[float]
    new_price: float
    change_type: str           # new / updated / deleted / unchanged


@dataclass
class DiffReport:
    supplier_code: str
    items_new: List[DiffItem] = field(default_factory=list)
    items_updated: List[DiffItem] = field(default_factory=list)
    items_deleted: List[DiffItem] = field(default_factory=list)
    items_unchanged: List[DiffItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items_new) + len(self.items_updated) + len(self.items_deleted) + len(self.items_unchanged)

    def summary(self) -> dict:
        return {
            "supplier_code": self.supplier_code,
            "new": len(self.items_new),
            "updated": len(self.items_updated),
            "deleted": len(self.items_deleted),
            "unchanged": len(self.items_unchanged),
            "total_parsed": len(self.items_new) + len(self.items_updated) + len(self.items_unchanged),
        }

    def preview(self, limit: int = 10) -> dict:
        """Первые N строк каждой категории для UI preview."""
        return {
            "new": [{"article": i.article, "name": i.name[:80], "price": i.new_price}
                    for i in self.items_new[:limit]],
            "updated": [{"article": i.article, "name": i.name[:80],
                         "old_price": i.old_price, "new_price": i.new_price}
                        for i in self.items_updated[:limit]],
            "deleted": [{"article": i.article, "name": i.name[:80], "price": i.old_price}
                        for i in self.items_deleted[:limit]],
        }


def build_diff(
    db: Session,
    parsed: List[ParsedProduct],
    supplier_code: str,
) -> DiffReport:
    """Сравнить parsed товары с тем что в БД для данного supplier_code."""
    # Загрузить существующие записи из БД
    existing: Dict[str, DBProduct] = {}
    rows = db.scalars(
        select(DBProduct).where(DBProduct.supplier_code == supplier_code)
    ).all()
    for row in rows:
        existing[row.article] = row

    parsed_map: Dict[str, ParsedProduct] = {p.article: p for p in parsed}
    report = DiffReport(supplier_code=supplier_code)

    # Новые и изменённые
    for article, item in parsed_map.items():
        if article not in existing:
            report.items_new.append(DiffItem(
                article=article,
                name=item.name,
                old_price=None,
                new_price=item.price_base,
                change_type="new",
            ))
        else:
            old = existing[article]
            old_price = float(old.price_base) if old.price_base else None
            if old_price is None or abs(old_price - item.price_base) > 0.01:
                report.items_updated.append(DiffItem(
                    article=article,
                    name=item.name,
                    old_price=old_price,
                    new_price=item.price_base,
                    change_type="updated",
                ))
            else:
                report.items_unchanged.append(DiffItem(
                    article=article,
                    name=item.name,
                    old_price=old_price,
                    new_price=item.price_base,
                    change_type="unchanged",
                ))

    # Удалённые (есть в БД, нет в новом прайсе)
    for article, row in existing.items():
        if article not in parsed_map:
            report.items_deleted.append(DiffItem(
                article=article,
                name=row.name,
                old_price=float(row.price_base) if row.price_base else None,
                new_price=0,
                change_type="deleted",
            ))

    return report
