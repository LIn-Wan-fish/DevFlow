from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_db
from app.schemas.workspace import PrFileOut, PrOut

router = APIRouter(prefix="/api/repos", tags=["PR 审查"])


@router.get("/{repo_id}/prs", summary="PR 列表(含高风险路径标记)")
def list_prs(repo_id: int = Path(..., description="仓库 ID"), db: Session = Depends(get_db)) -> dict:
    if db.get(m.Repo, repo_id) is None:
        raise HTTPException(status_code=404, detail=f"仓库 {repo_id} 不存在")

    rows = db.scalars(select(m.PullRequest).where(m.PullRequest.repo_id == repo_id)
                      .order_by(m.PullRequest.number.desc())).all()
    items = []
    for pr in rows:
        items.append(PrOut(
            id=pr.id, number=pr.number, title=pr.title, state=pr.state, merged=pr.merged,
            head_ref=pr.head_ref, base_ref=pr.base_ref,
            files=[PrFileOut(path=f.path, additions=f.additions, deletions=f.deletions,
                             is_high_risk=f.is_high_risk) for f in pr.files],
        ).model_dump())
    return {"items": items, "total": len(items)}