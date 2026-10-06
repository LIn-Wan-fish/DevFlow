from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_db
from app.schemas.workspace import IssueOut

router = APIRouter(prefix="/api/repos", tags=["issues"])

GROUP_KEYS = ("unarchived", "discussing", "pending_decision", "handled", "rejected", "closed")


@router.get("/{repo_id}/issues")
def list_issues(
    repo_id: int,
    state: str | None = None,
    assignee: str | None = None,
    q: str | None = None,
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