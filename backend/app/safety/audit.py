"""审计日志。

规则:只要碰过写操作 —— 无论是执行成功、被拒绝、还是越权尝试 —— 都要留痕。
只记成功的审计等于没有审计:出了问题最想知道的恰恰是「谁试过但没成功」。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditLog

# 允许的结果取值
EXECUTED = "executed"
REJECTED = "rejected"
DENIED = "denied"
FAILED = "failed"


def record(
    db: Session,
    *,
    draft_id: int | None,
    action: str,
    target: str = "",
    result: str,
    detail: str = "",
    actor_role: str = "",
) -> AuditLog:
    entry = AuditLog(
        draft_id=draft_id,
        action=action,
        target=target,
        result=result,
        detail=detail,
        actor_role=actor_role,
    )
    db.add(entry)
    db.commit()
    return entry