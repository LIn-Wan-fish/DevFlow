"""ContextAssembler:把仓库信息、历史对话、已确认记忆和证据组织成模型输入。

对应原文链路图的第 ② 段 —— 让 Agent 知道「当前在讨论哪个项目、什么问题」。
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.budget import AssembledContext, EvidenceItem, allocate
from app.core.memory import MemHub
from app.core.prompts.chat import CHAT_SYSTEM
from app.db import models as m


@dataclass
class ContextInfo:
    repo: str
    history_turns: int
    memory_hits: int
    compressed: list[str]
    budget_total: int
    budget_used: int
    used_segments: dict


class ContextAssembler:
    def __init__(self, hub: MemHub | None = None) -> None:
        self.hub = hub or MemHub()

    def assemble(
        self,
        db: Session,
        *,
        session_id: int | None,
        repo_id: int,
        question: str,
    ) -> tuple[list[BaseMessage], ContextInfo]:
        repo = db.get(m.Repo, repo_id)
        rows: list[m.Message] = []
        if session_id is not None:
            rows = list(db.scalars(
                select(m.Message).where(m.Message.session_id == session_id)
                .order_by(m.Message.id.asc())
            ).all())

        history = [
            {"role": row.role, "content": row.content}
            for row in rows
            if row.content
        ]

        memory_hits = self.hub.recall(db, repo_id=repo_id, query=question, top_k=5)
        evidence = [EvidenceItem(text=f"[已确认记忆] {hit.content}", score=hit.score)
                    for hit in memory_hits]

        assembled = AssembledContext(
            system=CHAT_SYSTEM,
            summary="",
            history=history,
            tool_results=[],
            evidence=evidence,
        )
        budgeted = allocate(assembled, settings.context_budget)

        messages: list[BaseMessage] = []
        for item in budgeted.history:
            content = str(item.get("content", ""))
            if item.get("role") == "assistant":
                messages.append(AIMessage(content))
            else:
                messages.append(HumanMessage(content))

        info = ContextInfo(
            repo=repo.full_name if repo else str(repo_id),
            history_turns=len(messages),
            memory_hits=len(budgeted.evidence),
            compressed=budgeted.compressed,
            budget_total=settings.context_budget,
            budget_used=budgeted.total_tokens,
            used_segments=budgeted.used_segments,
        )
        return messages, info