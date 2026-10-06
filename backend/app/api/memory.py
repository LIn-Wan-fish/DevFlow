"""记忆候选池与批准。未批准的候选不会参与召回。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.memory import MemHub
from app.db.session import get_db
from app.schemas.memory import (
    ApproveRequest,
    MemoryCandidateOut,
    MemoryEntryOut,
    MemoryOverview,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])
_hub = MemHub()


@router.get("/candidates", response_model=MemoryOverview)
def overview(repo_id: int = 1, db: Session = Depends(get_db)) -> MemoryOverview:
    candidates = _hub.pending(db, repo_id)
    entries = _hub.approved(db, repo_id)
    return MemoryOverview(
        candidates=[
            MemoryCandidateOut(id=c.id, content=c.content, confidence=c.confidence,
                               status=c.status, run_id=c.run_id)
            for c in candidates
        ],
        entries=[
            MemoryEntryOut(id=e.id, content=e.content, approved_by=e.approved_by,
                           source_candidate_id=e.source_candidate_id)
            for e in entries
        ],
    )


@router.post("/candidates/{candidate_id}/approve", response_model=MemoryEntryOut)
def approve(candidate_id: int, body: ApproveRequest | None = None,
            db: Session = Depends(get_db)) -> MemoryEntryOut:
    try:
        entry = _hub.approve(db, candidate_id,
                             approved_by=(body.approved_by if body else "member"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MemoryEntryOut(id=entry.id, content=entry.content, approved_by=entry.approved_by,
                          source_candidate_id=entry.source_candidate_id)


@router.post("/candidates/{candidate_id}/reject", response_model=MemoryCandidateOut)
def reject(candidate_id: int, db: Session = Depends(get_db)) -> MemoryCandidateOut:
    try:
        candidate = _hub.reject(db, candidate_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MemoryCandidateOut(id=candidate.id, content=candidate.content,
                              confidence=candidate.confidence, status=candidate.status,
                              run_id=candidate.run_id)