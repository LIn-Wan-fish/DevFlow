from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.agents.board import board
from app.db import models as m
from app.db.session import get_db
from app.observability.tracing import load_trace

router = APIRouter(prefix="/api/runs", tags=["运行轨迹"])


@router.get("/{run_id}", summary="运行详情(含工具调用与工作流轨迹)")
def get_run(run_id: int = Path(..., description="运行 ID"), db: Session = Depends(get_db)) -> dict:
    trace = load_trace(db, run_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"运行轨迹 {run_id} 不存在")
    return trace


def _finding_out(f: m.AgentFinding) -> dict:
    return {
        "id": f.id, "author": f.author, "topic": f.topic,
        "conclusion": f.conclusion, "evidence": f.evidence or [],
        "confidence": f.confidence, "status": f.status,
        "references": f.references or [], "supersedes_id": f.supersedes_id,
        "task_id": f.task_id,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@router.get("/{run_id}/findings", summary="这次运行的共享发现板(含协作图与分歧)")
def get_findings(run_id: int = Path(..., description="运行 ID"),
                 db: Session = Depends(get_db)) -> dict:
    """把一次运行里所有 Agent 的发现、它们之间的引用关系、以及分歧点一并返回。

    对应 Unity Version Control 的 **分支浏览器**:不只是"有哪些变更集",
    还要能看出**谁基于谁做的** —— 那才是协作的形状,而不只是一串流水账。

    `edges` 是引用关系的邻接表:`{"from": 后一条, "to": 被引用的那条}`。
    前端据此画图。
    """
    rows = board.read(db, run_id, exclude_superseded=False)
    edges = [
        {"from": f.id, "to": ref}
        for f in rows
        for ref in (f.references or [])
    ]
    dead = board.superseded_ids(db, run_id)
    return {
        "run_id": run_id,
        "findings": [_finding_out(f) for f in rows],
        # 未被推翻的那些才是当前有效的依据
        "active_finding_ids": [f.id for f in rows if f.id not in dead],
        "edges": edges,
        "conflicts": board.conflicting_topics(db, run_id),
        "authors": sorted({f.author for f in rows}),
    }