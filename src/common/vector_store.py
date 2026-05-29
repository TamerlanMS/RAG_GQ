"""
Два Pinecone-хранилища:
  - NamesVectorStore  — наименования товаров (русские описания)
  - ArticulVectorStore — артикулы (латинские коды: PP24-1UC5ES-D05, A9D31620...)

Функция is_articul() определяет тип запроса по эвристике.
"""
from __future__ import annotations

import re
from typing import List, Optional

from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from src.common.logger import logger
from src.settings.config import PineconeArticulSettings, PineconeSettings

# ─── Эвристика: артикул или наименование? ───────────────────

# Артикул: ≤30 символов, содержит цифры или латиницу, мало кириллицы
_CYRILLIC_RE = re.compile(r'[а-яёА-ЯЁ]')
_LATIN_DIGIT_RE = re.compile(r'[A-Za-z0-9]')

_DIGIT_RE = re.compile(r'\d')
_SEPARATOR_RE = re.compile(r'[-/_.]')

def is_articul(query: str) -> bool:
    """
    True если запрос похож на артикул, False если на наименование/бренд.

    Признаки артикула:
    - длина ≤ 30 символов
    - доля латиницы+цифр > 50%
    - кириллических букв < 3
    - ОБЯЗАТЕЛЬНО: содержит цифры ИЛИ разделители (-, /, _, .)
      Чистые буквенные слова (DKC, IEK, Lezard, Axolute) — это бренды/наименования, НЕ артикулы
    """
    q = query.strip()
    if len(q) > 30:
        return False
    cyrillic_count = len(_CYRILLIC_RE.findall(q))
    if cyrillic_count >= 3:
        return False
    # Чисто буквенная строка — бренд или наименование, не артикул
    has_digit = bool(_DIGIT_RE.search(q))
    has_separator = bool(_SEPARATOR_RE.search(q))
    if not has_digit and not has_separator:
        return False
    latin_digit_count = len(_LATIN_DIGIT_RE.findall(q))
    total = len(q.replace(' ', ''))
    if total == 0:
        return False
    return (latin_digit_count / total) > 0.5


# ─── Базовый класс ──────────────────────────────────────────

class _BaseVectorStore:
    def __init__(self, index_name: str, index_host: str, namespace: str,
                 embedding_model: str, dimension: int,
                 openai_api_key: str, pinecone_api_key: str,
                 search_k: int) -> None:
        self._namespace = namespace
        self._search_k = search_k
        self._index_name = index_name

        self._pc = Pinecone(api_key=pinecone_api_key)
        self._index = self._pc.Index(name=index_name, host=index_host)

        self._embedding = OpenAIEmbeddings(
            model=embedding_model,
            dimensions=dimension,
            openai_api_key=openai_api_key,
        )

        self._store = PineconeVectorStore(
            index=self._index,
            embedding=self._embedding,
            namespace=namespace,
        )

    def search(self, query: str) -> List[str]:
        """Векторный поиск. Возвращает список text-значений документов."""
        try:
            results = self._store.similarity_search(query, k=self._search_k)
            return [doc.page_content for doc in results]
        except Exception as e:
            logger.warning("Vector search error in %s: %s", self._index_name, e)
            return []

    def _delete_all(self) -> None:
        try:
            self._index.delete(delete_all=True, namespace=self._namespace)
        except Exception as e:
            logger.warning("Index delete error: %s", e)

    def rebuild(self, texts: List[str], metadatas: Optional[List[dict]] = None) -> str:
        if not texts:
            return "No texts provided."
        self._delete_all()
        try:
            self._store.add_texts(texts=texts, metadatas=metadatas or [{} for _ in texts],
                                  namespace=self._namespace)
            logger.info("Rebuilt %s index: %d items", self._index_name, len(texts))
            return f"Index '{self._index_name}' rebuilt: {len(texts)} items."
        except Exception as e:
            logger.error("Rebuild error for %s: %s", self._index_name, e)
            return f"Error rebuilding '{self._index_name}': {e}"


# ─── Индекс наименований ────────────────────────────────────

class NamesVectorStore(_BaseVectorStore):
    def __init__(self) -> None:
        cfg = PineconeSettings()
        super().__init__(
            index_name=cfg.index_name,
            index_host=cfg.index_host,
            namespace=cfg.namespace,
            embedding_model=cfg.embedding_model,
            dimension=cfg.dimension,
            openai_api_key=cfg.openai_api_key,
            pinecone_api_key=cfg.pinecone_api_key,
            search_k=cfg.search_k,
        )

    def search(self, query: str) -> List[dict]:
        """
        Векторный поиск по наименованиям.
        Возвращает List[dict] с полными данными товара из метаданных.
        """
        try:
            results = self._store.similarity_search(query, k=self._search_k)
            out = []
            for doc in results:
                m = doc.metadata or {}
                if m.get("name"):
                    out.append({
                        "name": m["name"],
                        "brend": m.get("brend") or None,
                        "articul": m.get("articul") or None,
                        "price": m.get("price") or None,
                        "quantity": m.get("quantity") or None,
                    })
                else:
                    # Старый формат — только page_content
                    out.append({"name": doc.page_content, "brend": None, "articul": None, "price": None, "quantity": None})
            return out
        except Exception as e:
            logger.warning("Vector search error in %s: %s", self._index_name, e)
            return []

    def rebuild_vector_store(
        self,
        products: Optional[List[dict]] = None,
        products_names: Optional[List] = None,
    ) -> str:
        """
        Пересборка индекса наименований.

        products: List[dict] — {name, brend, articul, price, quantity}
        products_names: устаревший параметр List[str], поддерживается для обратной совместимости.
        """
        if products is None and products_names is not None:
            products = [
                {"name": n, "brend": "", "articul": "", "price": "", "quantity": ""}
                for n in products_names if n
            ]
        if not products:
            return "No products provided."

        texts: List[str] = []
        metas: List[dict] = []
        for p in products:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            brend = (p.get("brend") or "").strip()
            articul = (p.get("articul") or "").strip()
            # Обогащённый текст: имя + бренд + артикул → лучший семантический поиск
            parts = [name]
            if brend:
                parts.append(f"Бренд: {brend}")
            if articul:
                parts.append(f"Арт: {articul}")
            texts.append(" | ".join(parts))
            metas.append({
                "name": name,
                "brend": brend,
                "articul": articul,
                "price": (p.get("price") or "").strip(),
                "quantity": (p.get("quantity") or "").strip(),
            })
        return self.rebuild(texts, metas)


# ─── Индекс артикулов ───────────────────────────────────────

class ArticulVectorStore(_BaseVectorStore):
    def __init__(self) -> None:
        cfg = PineconeArticulSettings()
        super().__init__(
            index_name=cfg.index_name,
            index_host=cfg.index_host,
            namespace=cfg.namespace,
            embedding_model=cfg.embedding_model,
            dimension=cfg.dimension,
            openai_api_key=cfg.openai_api_key,
            pinecone_api_key=cfg.pinecone_api_key,
            search_k=cfg.search_k,
        )

    def rebuild_articuls(self, articul_name_pairs: List[dict]) -> str:
        """
        articul_name_pairs: [{"articul": "PP24-1UC5ES-D05", "name": "...", "external_id": "..."}]
        Текст документа = артикул, метаданные = name + external_id.
        """
        texts = [p["articul"] for p in articul_name_pairs if p.get("articul")]
        metas = [{"name": p["name"], "external_id": p.get("external_id", "")}
                 for p in articul_name_pairs if p.get("articul")]
        return self.rebuild(texts, metas)

    def search_articul(self, query: str) -> List[dict]:
        """
        Возвращает [{articul, name, external_id}] — топ совпадений по артикулу.
        """
        try:
            results = self._store.similarity_search_with_score(query, k=self._search_k)
            out = []
            for doc, score in results:
                out.append({
                    "articul": doc.page_content,
                    "name": doc.metadata.get("name", ""),
                    "external_id": doc.metadata.get("external_id", ""),
                    "score": round(score, 4),
                })
            return out
        except Exception as e:
            logger.warning("Articul search error: %s", e)
            return []


# ─── Синглтоны ──────────────────────────────────────────────

vector_store = NamesVectorStore()
articul_store = ArticulVectorStore()
