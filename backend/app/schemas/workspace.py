from pydantic import BaseModel


class RepoOut(BaseModel):
    id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    is_github: bool = False


class HealthOut(BaseModel):
    repo: str
    open_issues: int
    prs_pending_review: int
    issues_resolved: int
    issues_rejected: int
    failed_ci: int
    merged_prs: int


class IssueOut(BaseModel):
    id: int
    number: int
    title: str
    state: str
    group: str
    labels: list[str] = []
    assignee: str | None = None
    excerpt: str = ""


class PrFileOut(BaseModel):
    path: str
    additions: int
    deletions: int
    is_high_risk: bool


class PrOut(BaseModel):
    id: int
    number: int
    title: str
    state: str
    merged: bool
    head_ref: str
    base_ref: str
    files: list[PrFileOut] = []


class CiOut(BaseModel):
    id: int
    number: int
    workflow: str
    branch: str
    conclusion: str
    duration_seconds: int


class SessionOut(BaseModel):
    id: int
    title: str
    repo_id: int


class RagQueryRequest(BaseModel):
    repo_id: int
    query: str
    top_k: int = 6


class RecallTestRequest(BaseModel):
    repo_id: int
    query: str
    top_k: int = 6


class DraftOut(BaseModel):
    id: int
    action: str
    target: str
    preview: str
    risk_level: str
    status: str
    requested_by_role: str