"""
Транслитерация: русский ↔ латиница.
Используется для повторного поиска товара когда первый поиск не дал результатов.
"""
from __future__ import annotations

# Русский → Латиница
_RU_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    # Заглавные
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
    "Е": "E", "Ё": "Yo", "Ж": "Zh", "З": "Z", "И": "I",
    "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N",
    "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
    "У": "U", "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch",
    "Ш": "Sh", "Щ": "Sch", "Ъ": "", "Ы": "Y", "Ь": "",
    "Э": "E", "Ю": "Yu", "Я": "Ya",
}

# Латиница → Русский (фонетически, для поиска)
_LAT_TO_RU: dict[str, str] = {
    "a": "а", "b": "б", "c": "с", "d": "д", "e": "е",
    "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "кс", "y": "й",
    "z": "з",
    "A": "А", "B": "Б", "C": "С", "D": "Д", "E": "Е",
    "F": "Ф", "G": "Г", "H": "Х", "I": "И", "J": "Дж",
    "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О",
    "P": "П", "Q": "К", "R": "Р", "S": "С", "T": "Т",
    "U": "У", "V": "В", "W": "В", "X": "Кс", "Y": "Й",
    "Z": "З",
}

# Точные переводы часто встречающихся брендов (в обе стороны)
_BRAND_MAP: dict[str, str] = {
    # Кириллица → латиница
    "сонекс": "sonex",
    "световые технологии": "light technologies",
    "зэта": "zeta",
    "кэаз": "keaz",
    "рубеж": "rubezh",
    "стендинг": "stending",
    "тромбон": "trombon",
    "эра": "era",
    "эгида": "egida",
    "модус трейд": "modus trade",
    # Латиница → кириллица
    "sonex": "сонекс",
    "era": "эра",
    "egida": "эгида",
    "keaz": "кэаз",
    "zeta": "зэта",
    "schneider": "schneider electric",
    "шнайдер": "schneider electric",
    "легран": "legrand",
    "лежран": "legrand",
    "iek": "iek/itk",
    "itk": "iek/itk",
    "иек": "iek/itk",
    "hv": "hikvision",
    "хиквижн": "hikvision",
}


def ru_to_lat(text: str) -> str:
    """Транслитерация русского текста в латиницу."""
    result = []
    for ch in text:
        result.append(_RU_TO_LAT.get(ch, ch))
    return "".join(result)


def lat_to_ru(text: str) -> str:
    """Транслитерация латинского текста в русский (посимвольно)."""
    result = []
    for ch in text:
        result.append(_LAT_TO_RU.get(ch, ch))
    return "".join(result)


def get_search_variants(query: str) -> list[str]:
    """
    Возвращает список вариантов запроса для поиска:
    оригинал + транслитерированный вариант + точный перевод бренда (если есть).
    """
    variants = [query]

    # Проверяем точный перевод бренда
    lower = query.strip().lower()
    if lower in _BRAND_MAP:
        variants.append(_BRAND_MAP[lower])

    # Определяем направление транслитерации
    has_cyrillic = any("Ѐ" <= ch <= "ӿ" for ch in query)
    has_latin = any("a" <= ch.lower() <= "z" for ch in query)

    if has_cyrillic and not has_latin:
        # Русский → транслит на латиницу
        variants.append(ru_to_lat(query))
    elif has_latin and not has_cyrillic:
        # Латиница → транслит на русский
        variants.append(lat_to_ru(query))

    # Убираем дубликаты, сохраняя порядок
    seen: set[str] = set()
    unique = []
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower())
            unique.append(v)
    return unique
