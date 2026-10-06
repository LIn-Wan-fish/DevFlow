from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.observability.tracing import load_trace

router = APIRouter(prefix="/api/runs", tags=["运行轨迹"])


@router.get("/{run_id}", summary="运行详情(含工具调用与工作流轨迹)")
def get_run(run_id: int = Path(..., description="运行 ID"), db: Session = Depends(get_db)) -> dict:
    trace = load_trace(db, run_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"运行轨迹 {run_id} 不存在")
    return trace