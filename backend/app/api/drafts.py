"""草稿列表与人工确认。confirm 才真正执行写操作。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_role
from app.db import models as m
from app.db.session import get_db
from app.safety import drafts as draft_store
from app.safety.policy import PermissionDenied
from app.schemas.workspace import DraftOut

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def _to_out(draft: m.ActionDraft) -> DraftOut:
    return DraftOut(id=draft.id, action=draft.action, target=draft.target,
                    preview=draft.preview, risk_level=draft.risk_level,
                    status=draft.status, requested_by_role=draft.requested_by_role)


@router.get("", response_model=list[DraftOut])
def list_drafts(status: str | None = None, repo_id: int | None = None,
                db: Session = Depends(get_db)) -> list[DraftOut]:
    query = select(m.ActionDraft)
    if status:
        query = query.where(m.ActionDraft.status == status)
    if repo_id is not None:
        query = query.where(m.ActionDraft.repo_id == repo_id)
    rows = db.scalars(query.order_by(m.ActionDraft.id.desc())).all()
    return [_to_out(d) for d in rows]


@router.post("/{draft_id}/confirm", response_model=DraftOut)
def confirm(draft_id: int, role: str = Depends(get_role),
            db: Session = Depends(get_db)) -> DraftOut:
    try:
        draft = draft_store.confirm(db, draft_id, role=role)
    except draft_store.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDenied as exc:
        # 越权已经记过审计,这里只负责回 403 并说明原因
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except draft_store.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except draft_store.ExecutionFailed as exc:
        # 502 而不是 500:这是**上游**(GitHub)拒绝或不可达,
        # 不是本服务的内部错误。草稿已标 failed、审计已留痕,
        # 调用方需要看到具体原因(最常见的是一句话:令牌缺哪个权限)。
        raise HTTPException(
            status_code=502,
            detail=f"写操作执行失败(草稿已标记 failed 并留痕):{exc}",
        ) from exc
    return _to_out(draft)


@router.post("/{draft_id}/reject", response_model=DraftOut)
def reject(draft_id: int, role: str = Depends(get_role),
           db: Session = Depends(get_db)) -> DraftOut:
    try:
        draft = draft_store.reject(db, draft_id, role=role)
    except draft_store.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except draft_store.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_out(draft)


@router.get("/audit", response_model=list[dict])
def audit(repo_id: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(100)).all()
    return [
        {"id": row.id, "draft_id": row.draft_id, "action": row.action, "target": row.target,
         "result": row.result, "detail": row.detail, "actor_role": row.actor_role,
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]