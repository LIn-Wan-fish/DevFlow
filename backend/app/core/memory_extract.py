"""从一次运行的结果里提取「值得跨会话复用」的经验,写入候选池。

候选池不是日志。把每次运行的全文倒进去,只会让「人工批准」变成走过场,
最后没人看 —— 那这道闸门就白设了。所以这里只沉淀**证据明确、格式稳定**的结论。

注意:这里只**沉淀**,不生效。未批准的候选绝不参与召回。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.memory import MemHub
from app.db.models import MemoryCandidate, MemoryEntry, MemoryStatus

MAX_CONTENT_CHARS = 300


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_CONTENT_CHARS else text[:MAX_CONTENT_CHARS] + "…"


def extract_candidates(outcome: Any) -> list[dict]:
    """返回 [{content, confidence}]。规则刻意收窄,只留两类。

    1) CI 根因且置信度高 —— 同类问题下次大概率还会遇到,复用价值最高
    2) 多 Agent 工作流的发布/合并判断结论 —— 记录当时的取舍与理由
    """
    items: list[dict] = []

    for record in getattr(outcome, "tool_calls", []):
        if getattr(record, "error", None):
            continue
        data = getattr(record, "data", None) or {}

        if record.tool == "debug_ci":
            root_cause = data.get("root_cause")
            if root_cause and data.get("confidence") == "high":
                number = data.get("number")
                items.append({
                    "content": _clip(f"CI #{number} 的失败根因:{root_cause}"),
                    "confidence": 0.8,
                })

        elif record.tool == "run_workflow":
            conclusion = data.get("conclusion")
            if conclusion:
                conflicts = data.get("conflicts") or []
                items.append({
                    "content": _clip(f"研发协作判断结论:{conclusion}"),
                    # 有冲突未消解时降低置信度 —— 这种结论更该被人工仔细看
                    "confidence": 0.6 if conflicts else 0.8,
                })

    # 去重:同一次运行里重复的结论只留一条
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        if item["content"] in seen:
            continue
        seen.add(item["content"])
        unique.append(item)
    return unique


def existing_contents(db: Session, repo_id: int) -> set[str]:
    """候选池 + 已生效记忆里的全部内容,用于跨运行去重。"""
    contents = set()
    for row in db.scalars(
        select(MemoryCandidate).where(MemoryCandidate.repo_id == repo_id)
    ).all():
        contents.add(row.content)
    for row in db.scalars(select(MemoryEntry).where(MemoryEntry.repo_id == repo_id)).all():
        contents.add(row.content)
    return contents


def deposit(
    db: Session,
    outcome: Any,
    *,
    repo_id: int,
    session_id: int | None,
    run_id: int | None,
    hub: MemHub | None = None,
) -> list[MemoryCandidate]:
    """把这次运行里值得复用的经验写进候选池(待人工批准)。"""
    hub = hub or MemHub()
    known = existing_contents(db, repo_id)
    created: list[MemoryCandidate] = []

    for item in extract_candidates(outcome):
        if item["content"] in known:
            continue  # 同一条经验不重复进候选池
        known.add(item["content"])
        created.append(hub.record_candidate(
            db, repo_id=repo_id, session_id=session_id, run_id=run_id,
            content=item["content"], confidence=item["confidence"],
        ))
    return created


def pending_count(db: Session, repo_id: int) -> int:
    return len([
        row for row in db.scalars(
            select(MemoryCandidate).where(
                MemoryCandidate.repo_id == repo_id,
                MemoryCandidate.status == MemoryStatus.PENDING.value,
            )
        ).all()
    ])