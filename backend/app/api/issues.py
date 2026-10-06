from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_db
from app.schemas.workspace import IssueOut

router = APIRouter(prefix="/api/repos", tags=["Issue 分诊"])

GROUP_KEYS = ("unarchived", "discussing", "pending_decision", "handled", "rejected", "closed")


@router.get("/{repo_id}/issues", summary="Issue 列表(分组计数 + 状态/负责人/关键词筛选)")
def list_issues(
    repo_id: int = Path(..., description="仓库 ID"),
    state: str | None = Query(None, description="按状态筛选,如 open / closed"),
    assignee: str | None = Query(None, description="按负责人筛选"),
    q: str | None = Query(None, description="标题/正文关键词"),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(m.Repo, repo_id) is None:
        raise HTTPException(status_code=404, detail=f"仓库 {repo_id} 不存在")

    query = select(m.Issue).where(m.Issue.repo_id == repo_id)
    if state:
        query = query.where(m.Issue.state == state)
    if assignee:
        query = query.where(m.Issue.assignee == assignee)
    if q:
        like = f"%{q}%"
        query = query.where(or_(m.Issue.title.ilike(like), m.Issue.body.ilike(like)))

    rows = db.scalars(query.order_by(m.Issue.number.desc())).all()
    all_rows = db.scalars(select(m.Issue).where(m.Issue.repo_id == repo_id)).all()

    groups = {key: 0 for key in GROUP_KEYS}
    for row in all_rows:
        groups[row.group] = groups.get(row.group, 0) + 1

    return {
        "items": [
            IssueOut(
                id=row.id, number=row.number, title=row.title, state=row.state,
                group=row.group, labels=list(row.labels or []), assignee=row.assignee,
                excerpt=(row.body or "").replace("\n", " ")[:120],
            ).model_dump()
            for row in rows
        ],
        "groups": groups,
        "total": len(all_rows),
    }