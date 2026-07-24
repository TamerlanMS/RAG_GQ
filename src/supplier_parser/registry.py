"""Реестр парсеров поставщиков."""
from __future__ import annotations

from typing import Dict, Optional, Type

from src.supplier_parser.parsers.base import BaseParser
from src.supplier_parser.parsers.himel import HimelParser
from src.supplier_parser.parsers.dkc import DKCParser
from src.supplier_parser.parsers.iek import IEKParser
from src.supplier_parser.parsers.ekf import EKFParser
from src.supplier_parser.parsers.schneider import SchneiderParser
from src.supplier_parser.parsers.legrand import LegrandParser

_REGISTRY: Dict[str, Type[BaseParser]] = {
    "himel":     HimelParser,
    "dkc":       DKCParser,
    "iek":       IEKParser,
    "ekf":       EKFParser,
    "schneider": SchneiderParser,
    "legrand":   LegrandParser,
}


def get_parser(supplier_code: str) -> Optional[BaseParser]:
    cls = _REGISTRY.get(supplier_code.lower())
    return cls() if cls else None


def list_suppliers():
    return list(_REGISTRY.keys())
