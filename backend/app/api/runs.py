from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability.tracing import load_trace

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    trace = load_trace(db, run_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"运行轨迹 {run_id} 不存在")
    return trace