"""会话记忆与跨会话 MemHub。

三段式:沉淀(候选)→ 人工批准 → 召回。
未批准的候选**绝不参与召回** —— 这是防止一次错误结论长期污染后续所有会话的闸门。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MemoryCandidate, MemoryEntry, MemoryStatus
from app.rag.rerank import strong_terms


@dataclass
class MemoryHit:
    entry_id: int
    content: str
    score: float
    source: str = "memory"  # 与文档证据区分,前端要分别展示
    approved_by: str = ""


def _terms(text: str) -> list[str]:
    """记忆召回用的词项。

    复用 RAG 的强词项切分(中文双字 + 长度 >=2 的英文词)。

    这里**曾经**用 `text.split()` —— 中文没有空格,整句会变成一个词项,
    于是「登录接口变更」匹配不上「登录接口的变更说明」这类内容,
    中文记忆基本召不回。而验收当时能过,只是因为候选内容里恰好带了
    "CI"、"#512" 这类 ASCII 分词。同一个错误在 RAG 里修过一次,
    在记忆这条路径上又犯了一遍。
    """
    return strong_terms(text)


class MemHub:
    # ------------------------------------------------------------------ 沉淀

    def record_candidate(
        self,
        db: Session,
        *,
        repo_id: int,
        session_id: int | None,
        run_id: int | None,
        content: str,
        confidence: float = 0.5,
    ) -> MemoryCandidate:
        candidate = MemoryCandidate(
            repo_id=repo_id,
            session_id=session_id,
            run_id=run_id,
            content=content,
            confidence=confidence,
            status=MemoryStatus.PENDING.value,
        )
        db.add(candidate)
        db.commit()
        return candidate

    # ------------------------------------------------------------------ 批准

    def approve(self, db: Session, candidate_id: int, *, approved_by: str) -> MemoryEntry:
        candidate = db.get(MemoryCandidate, candidate_id)
        if candidate is None:
            raise LookupError(f"记忆候选 {candidate_id} 不存在")

        # 幂等:重复批准返回同一条,不产生第二份副本
        existing = db.scalar(
            select(MemoryEntry).where(MemoryEntry.source_candidate_id == candidate_id)
        )
        if existing is not None:
            return existing

        entry = MemoryEntry(
            repo_id=candidate.repo_id,
            content=candidate.content,
            source_candidate_id=candidate.id,
            approved_by=approved_by,
            milvus_id=None,
        )
        candidate.status = MemoryStatus.APPROVED.value
        db.add(entry)
        db.commit()
        return entry

    def reject(self, db: Session, candidate_id: int) -> MemoryCandidate:
        candidate = db.get(MemoryCandidate, candidate_id)
        if candidate is None:
            raise LookupError(f"记忆候选 {candidate_id} 不存在")
        candidate.status = MemoryStatus.REJECTED.value
        db.commit()
        return candidate

    # ------------------------------------------------------------------ 召回

    def recall(self, db: Session, *, repo_id: int, query: str, top_k: int = 5) -> list[MemoryHit]:
        entries = db.scalars(
            select(MemoryEntry).where(MemoryEntry.repo_id == repo_id)
        ).all()
        if not entries:
            return []

        terms = _terms(query)
        if not terms:
            return []

        hits: list[MemoryHit] = []
        for entry in entries:
            lowered = entry.content.lower()
            score = sum(1 for term in terms if term in lowered)
            if score:
                hits.append(MemoryHit(entry_id=entry.id, content=entry.content,
                                      score=float(score), approved_by=entry.approved_by))
        hits.sort(key=lambda h: (-h.score, h.entry_id))
        return hits[:top_k]

    def pending(self, db: Session, repo_id: int) -> list[MemoryCandidate]:
        return list(db.scalars(
            select(MemoryCandidate).where(
                MemoryCandidate.repo_id == repo_id,
                MemoryCandidate.status == MemoryStatus.PENDING.value,
            )
        ).all())

    def approved(self, db: Session, repo_id: int) -> list[MemoryEntry]:
        return list(db.scalars(
            select(MemoryEntry).where(MemoryEntry.repo_id == repo_id)
        ).all())