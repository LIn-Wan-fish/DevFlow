from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_db
from app.schemas.workspace import CiOut

router = APIRouter(prefix="/api/repos", tags=["CI 排障"])


@router.get("/{repo_id}/ci", summary="CI 运行列表")
def list_ci(repo_id: int = Path(..., description="仓库 ID"), db: Session = Depends(get_db)) -> dict:
    if db.get(m.Repo, repo_id) is None:
        raise HTTPException(status_code=404, detail=f"仓库 {repo_id} 不存在")

    rows = db.scalars(select(m.CiRun).where(m.CiRun.repo_id == repo_id)
                      .order_by(m.CiRun.number.desc())).all()
    items = [
        CiOut(id=r.id, number=r.number, workflow=r.workflow, branch=r.branch,
              conclusion=r.conclusion, duration_seconds=r.duration_seconds).model_dump()
        for r in rows
    ]
    return {"items": items, "total": len(items)}