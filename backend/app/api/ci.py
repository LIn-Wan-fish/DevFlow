from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_db
from app.schemas.workspace import CiOut

router = APIRouter(prefix="/api/repos", tags=["ci"])


@router.get("/{repo_id}/ci")
def list_ci(repo_id: int, db: Session = Depends(get_db)) -> dict:
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