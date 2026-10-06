"""混合检索:向量召回 + 关键词召回落,RRF 融合,再重排。

两条召回通道刻意独立 —— 向量擅长语义近似,关键词擅长精确命中
(比如 "refresh_token" 这种标识符)。只留一条都会漏。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.embeddings import embed_query
from app.db import models as m
from app.rag.rerank import rerank, strong_terms
from app.rag.vectorstore import get_vector_store

RRF_K = 60
VECTOR_LIMIT = 20
KEYWORD_LIMIT = 20
FUSE_LIMIT = 10

_ASCII_TERM_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass
class Evidence:
    chunk_id: int
    repo_id: int
    doc_path: str
    heading_path: str
    content: str
    score: float
    source: str = "document"  # document | memory

    @property
    def citation(self) -> str:
        return f"{self.doc_path} > {self.heading_path}" if self.heading_path else self.doc_path


def query_terms(query: str) -> list[str]:
    """关键词召回用的词项。

    中文必须切成双字,不能把整段汉字当成一个词:
    否则 "登录接口变更" 会变成一个词项,SQL LIKE 永远匹配不上 ——
    文档里写的是 "登录接口" 和 "v1.2 变更",两段本来就分开。
    """
    lowered = (query or "").lower()
    terms = _ASCII_TERM_RE.findall(lowered)
    for run in _CJK_RUN_RE.findall(lowered):
        if len(run) == 1:
            terms.append(run)
        else:
            terms.extend(run[i : i + 2] for i in range(len(run) - 1))
    return list(dict.fromkeys(terms))


def rrf_fuse(*ranked_lists: list, k: int = RRF_K) -> list[tuple:]:
    """Reciprocal Rank Fusion:score(d) = Σ 1/(k + rank_i(d))。

    纯函数,先单独测透再上库 —— 融合公式写错的话,后面的重排再准也没用。
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def vector_search(repo_id: int, query: str, limit: int = VECTOR_LIMIT) -> list[int]:
    store = get_vector_store()
    hits = store.search(embed_query(query), repo_id=repo_id, limit=limit)
    return [chunk_id for chunk_id, _ in hits]


def keyword_search(db: Session, repo_id: int, query: str, limit: int = KEYWORD_LIMIT) -> list[int]:
    """关键词召回。

    筛选用 SQL(PostgreSQL / SQLite 都走得到索引),打分按词项命中数在 Python 侧算,
    保证两种方言下行为一致、可单测。生产若换 tsvector/BM25,只需替换本函数。
    """
    terms = query_terms(query)
    if not terms:
        return []
    conditions = [m.Chunk.content.ilike(f"%{term}%") for term in terms]
    rows = db.scalars(
        select(m.Chunk).where(m.Chunk.repo_id == repo_id, or_(*conditions)).limit(200)
    ).all()

    scored: list[tuple[int, int]] = []
    for chunk in rows:
        lowered = chunk.content.lower()
        hits = sum(1 for term in terms if term.lower() in lowered)
        if hits:
            scored.append((chunk.id, hits))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return [chunk_id for chunk_id, _ in scored[:limit]]


def _load_evidence(db: Session, repo_id: int, chunk_ids: list[int], scores: dict[int, float]) -> list[Evidence]:
    if not chunk_ids:
        return []
    rows = db.scalars(
        select(m.Chunk).where(m.Chunk.repo_id == repo_id, m.Chunk.id.in_(chunk_ids))
    ).all()
    by_id = {c.id: c for c in rows}
    docs = {d.id: d.path for d in db.scalars(
        select(m.Document).where(m.Document.repo_id == repo_id)
    ).all()}

    evidence: list[Evidence] = []
    for chunk_id in chunk_ids:
        chunk = by_id.get(chunk_id)
        if chunk is None:
            continue
        evidence.append(
            Evidence(
                chunk_id=chunk.id,
                repo_id=repo_id,
                doc_path=docs.get(chunk.document_id, ""),
                heading_path=chunk.heading_path,
                content=chunk.content,
                score=scores.get(chunk_id, 0.0),
            )
        )
    return evidence


def corpus_idf(db: Session, repo_id: int) -> dict[str, float]:
    """按仓库语料算 IDF。

    Demo 的语料只有几十个切分,直接全量扫一遍就够;
    生产环境应当由 IR 索引(BM25 / tsvector)直接提供。

    为什么需要它:不加权的话,"量子纠缠模块 实现" 会靠 "模块" + "实现"
    这两个常见词凑过阈值,把无关文档当成证据交出去 —— 实测踩到过。
    """
    rows = db.execute(select(m.Chunk.content).where(m.Chunk.repo_id == repo_id)).all()
    document_frequency: Counter[str] = Counter()
    for (content,) in rows:
        document_frequency.update(set(strong_terms(content)))
    total = len(rows)
    return {
        term: math.log((total + 1) / (count + 1)) + 1.0
        for term, count in document_frequency.items()
    }

def hybrid_search(db: Session, repo_id: int, query: str, top_k: int = 6) -> list[Evidence]:
    """空结果就返回空 —— 不允许用低相关文档兜底,那等于让模型自由发挥。"""
    vec_ids = vector_search(repo_id, query)
    kw_ids = keyword_search(db, repo_id, query)
    fused = rrf_fuse(vec_ids, kw_ids)
    if not fused:
        return []

    candidate_ids = [chunk_id for chunk_id, _ in fused[:FUSE_LIMIT]]
    rows = db.scalars(
        select(m.Chunk).where(m.Chunk.repo_id == repo_id, m.Chunk.id.in_(candidate_ids))
    ).all()
    contents = {c.id: c.content for c in rows}

    ranked = rerank(query, [(cid, contents.get(cid, "")) for cid in candidate_ids], top_k,
                    idf=corpus_idf(db, repo_id))
    # 重排后全为 0 分,说明只是「词面上勉强包含」,不应作为证据交付
    if ranked and all(item.score <= 0 for item in ranked):
        return []
    fused_scores = dict(fused)
    ordered = [item.key for item in ranked]
    return _load_evidence(db, repo_id, ordered, {cid: fused_scores.get(cid, 0.0) for cid in ordered})