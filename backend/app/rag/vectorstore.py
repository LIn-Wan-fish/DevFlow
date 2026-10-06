"""向量存储抽象。

抽这一层是为了让单测不依赖 Milvus:测试通过 set_vector_store(InMemoryVectorStore())
换掉实现,业务代码一行都不用改。
"""

from __future__ import annotations

import math
import threading
from typing import Protocol

from app.core.embeddings import EMBED_DIM


class VectorStore(Protocol):
    def ensure_collection(self) -> None: ...

    def upsert(self, ids: list[int], repo_ids: list[int], vectors: list[list[float]]) -> None: ...

    def delete_repo(self, repo_id: int) -> None: ...

    def search(
        self, vector: list[float], repo_id: int, limit: int
    ) -> list[tuple[int, float]]: ...


class InMemoryVectorStore:
    """进程内实现:测试用,也用于 Milvus 不可用时的降级说明。"""

    def __init__(self) -> None:
        self._rows: dict[int, tuple[int, list[float]]] = {}
        self._lock = threading.Lock()

    def ensure_collection(self) -> None:  # noqa: D102
        return None

    def upsert(self, ids, repo_ids, vectors) -> None:  # noqa: ANN001, D102
        with self._lock:
            for i, repo_id, vec in zip(ids, repo_ids, vectors):
                self._rows[i] = (repo_id, vec)

    def delete_repo(self, repo_id: int) -> None:  # noqa: D102
        with self._lock:
            self._rows = {k: v for k, v in self._rows.items() if v[0] != repo_id}

    def search(self, vector, repo_id, limit):  # noqa: ANN001, D102
        def cos(a: list[float], b: list[float]) -> float:
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(x * x for x in b)) or 1.0
            return sum(x * y for x, y in zip(a, b)) / (na * nb)

        with self._lock:
            scored = [
                (chunk_id, cos(vector, vec))
                for chunk_id, (rid, vec) in self._rows.items()
                if rid == repo_id
            ]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:limit]


class MilvusVectorStore:
    """Milvus 实现。检索一律带 repo_id 过滤,跨仓库内容不得进入证据集。"""

    def __init__(self, uri: str, collection: str, dim: int = EMBED_DIM) -> None:
        from pymilvus import MilvusClient

        self._client = MilvusClient(uri=uri)
        self._collection = collection
        self._dim = dim

    def ensure_collection(self) -> None:
        from pymilvus import DataType

        if self._client.has_collection(self._collection):
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("repo_id", DataType.INT64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._dim)
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="IVF_FLAT",
                               metric_type="COSINE", params={"nlist": 128})
        self._client.create_collection(self._collection, schema=schema,
                                       index_params=index_params)

    def upsert(self, ids, repo_ids, vectors) -> None:  # noqa: ANN001
        rows = [{"id": i, "repo_id": r, "vector": v} for i, r, v in zip(ids, repo_ids, vectors)]
        if rows:
            self._client.upsert(collection_name=self._collection, data=rows)

    def delete_repo(self, repo_id: int) -> None:
        self._client.delete(collection_name=self._collection, filter=f"repo_id == {repo_id}")

    def search(self, vector, repo_id, limit):  # noqa: ANN001
        res = self._client.search(
            collection_name=self._collection,
            data=[vector],
            filter=f"repo_id == {repo_id}",
            limit=limit,
            output_fields=["repo_id"],
            search_params={"metric_type": "COSINE"},
        )
        if not res:
            return []
        return [(int(hit["id"]), float(hit["distance"])) for hit in res[0]]


_store: VectorStore | None = None


def set_vector_store(store: VectorStore | None) -> None:
    """测试与启动流程用来替换实现。"""
    global _store
    _store = store


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        from app.config import settings

        _store = MilvusVectorStore(settings.milvus_uri, settings.milvus_collection)
    return _store