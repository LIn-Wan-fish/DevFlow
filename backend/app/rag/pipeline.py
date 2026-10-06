"""对外统一检索入口,含召回测试所需的四阶段中间结果。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.rag.retriever import (
    FUSE_LIMIT,
    Evidence,
    hybrid_search,
    keyword_search,
    rrf_fuse,
    vector_search,
)


@dataclass
class RecallTrace:
    """召回测试:一次看全切分 / 向量召回 / 关键词召回 / 融合重排。

    存在的意义是回答「检索没找到内容时,到底是切分坏了、排序坏了,
    还是过滤把正确结果滤掉了」—— 没有这四个阶段,就只能靠猜。
    """

    query: str
    chunks: list[dict] = field(default_factory=list)
    vector_hits: list[dict] = field(default_factory=list)
    keyword_hits: list[dict] = field(default_factory=list)
    fused_reranked: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _brief(db: Session, repo_id: int, chunk_ids: list[int]) -> list[dict]:
    if not chunk_ids:
        return []
    rows = db.scalars(
        select(m.Chunk).where(m.Chunk.repo_id == repo_id, m.Chunk.id.in_(chunk_ids))
    ).all()
    by_id = {c.id: c for c in rows}
    docs = {d.id: d.path for d in db.scalars(
        select(m.Document).where(m.Document.repo_id == repo_id)
    ).all()}
    out = []
    for chunk_id in chunk_ids:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        out.append(
            {
                "chunk_id": chunk.id,
                "doc_path": docs.get(chunk.document_id, ""),
                "heading_path": chunk.heading_path,
                "preview": chunk.content[:120],
                "token_count": chunk.token_count,
            }
        )
    return out


def search_with_trace(db: Session, repo_id: int, query: str, top_k: int = 6) -> RecallTrace:
    vec_ids = vector_search(repo_id, query)
    kw_ids = keyword_search(db, repo_id, query)
    fused = rrf_fuse(vec_ids, kw_ids)
    fused_ids = [chunk_id for chunk_id, _ in fused[:FUSE_LIMIT]]
    final = hybrid_search(db, repo_id, query, top_k=top_k)

    return RecallTrace(
        query=query,
        chunks=_brief(db, repo_id, fused_ids),
        vector_hits=_brief(db, repo_id, vec_ids[:10]),
        keyword_hits=_brief(db, repo_id, kw_ids[:10]),
        fused_reranked=[
            {
                "chunk_id": ev.chunk_id,
                "doc_path": ev.doc_path,
                "heading_path": ev.heading_path,
                "score": round(ev.score, 6),
                "preview": ev.content[:120],
            }
            for ev in final
        ],
    )