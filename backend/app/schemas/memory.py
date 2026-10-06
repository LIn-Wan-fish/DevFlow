from pydantic import BaseModel


class MemoryCandidateOut(BaseModel):
    id: int
    content: str
    confidence: float
    status: str
    run_id: int | None = None


class MemoryEntryOut(BaseModel):
    id: int
    content: str
    approved_by: str
    source_candidate_id: int | None = None


class ApproveRequest(BaseModel):
    approved_by: str = "member"


class MemoryOverview(BaseModel):
    candidates: list[MemoryCandidateOut]
    entries: list[MemoryEntryOut]