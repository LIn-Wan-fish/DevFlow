from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.github.conclusions import healthy_filter
from app.db.session import get_db
from app.repos import service as repo_service
from app.schemas.workspace import HealthOut, RepoOut, SessionOut

router = APIRouter(prefix="/api/repos", tags=["仓库"])


def _require_repo(db: Session, repo_id: int) -> m.Repo:
    repo = db.get(m.Repo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"仓库 {repo_id} 不存在")
    return repo


def health_of(db: Session, repo_id: int) -> dict:
    def count(model, *conditions) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0

    repo = db.get(m.Repo, repo_id)
    return {
        "repo": repo.full_name if repo else str(repo_id),
        "open_issues": count(m.Issue, m.Issue.repo_id == repo_id, m.Issue.state == "open"),
        "prs_pending_review": count(m.PullRequest, m.PullRequest.repo_id == repo_id,
                                    m.PullRequest.state == "open",
                                    m.PullRequest.merged.is_(False)),
        "issues_resolved": count(m.Issue, m.Issue.repo_id == repo_id, m.Issue.group == "handled"),
        "issues_rejected": count(m.Issue, m.Issue.repo_id == repo_id, m.Issue.group == "rejected"),
        "failed_ci": count(m.CiRun, m.CiRun.repo_id == repo_id, healthy_filter(m.CiRun.conclusion)),
        "merged_prs": count(m.PullRequest, m.PullRequest.repo_id == repo_id,
                            m.PullRequest.merged.is_(True)),
    }


@router.get("", response_model=list[RepoOut], summary="仓库列表")
def list_repos(db: Session = Depends(get_db)) -> list[RepoOut]:
    repos = db.scalars(select(m.Repo).order_by(m.Repo.id)).all()
    return [
        RepoOut(id=r.id, owner=r.owner, name=r.name, full_name=r.full_name,
                default_branch=r.default_branch, is_github=r.is_github)
        for r in repos
    ]


@router.get("/{repo_id}/health", response_model=HealthOut, summary="仓库健康总览(右栏六项统计)")
def repo_health(repo_id: int = Path(..., description="仓库 ID"), db: Session = Depends(get_db)) -> HealthOut:
    _require_repo(db, repo_id)
    return HealthOut(**health_of(db, repo_id))


@router.get("/{repo_id}/sessions", response_model=list[SessionOut], summary="会话列表")
def list_sessions(repo_id: int = Path(..., description="仓库 ID"), db: Session = Depends(get_db)) -> list[SessionOut]:
    _require_repo(db, repo_id)
    rows = db.scalars(select(m.Session).where(m.Session.repo_id == repo_id)
                      .order_by(m.Session.id)).all()
    return [SessionOut(id=s.id, title=s.title, repo_id=s.repo_id) for s in rows]

# --------------------------------------------------------------------------- 添加与同步


class AddRepoRequest(BaseModel):
    full_name: str
    sync: bool = True


@router.post("", response_model=RepoOut, status_code=201, summary="添加仓库(按 owner/name,幂等)")
async def add_repo(body: AddRepoRequest, db: Session = Depends(get_db)) -> RepoOut:
    """添加一个 GitHub 仓库并同步数据。

    与内置快照仓库是**并列的项目**,互不影响 —— 每个仓库的数据来源写在 `is_github` 上,
    不会出现「同一个仓库一半快照一半真实」的混用。
    """
    try:
        repo, counts = await repo_service.add_repo(db, body.full_name, sync=body.sync)
    except repo_service.RepoAddError as exc:
        # 把真实原因原样回给用户:是没配令牌、仓库不存在,还是权限不够,三者区别很大
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return RepoOut(id=repo.id, owner=repo.owner, name=repo.name,
                   full_name=repo.full_name, default_branch=repo.default_branch,
                   is_github=repo.is_github)


@router.post("/{repo_id}/sync", summary="重新同步仓库数据(快照仓库会如实拒绝)")
async def sync_repo(repo_id: int = Path(..., description="仓库 ID"),
                    db: Session = Depends(get_db)) -> dict:
    repo = _require_repo(db, repo_id)
    try:
        counts = await repo_service.resync(db, repo)
    except repo_service.RepoAddError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return {"repo": repo.full_name, "counts": counts}