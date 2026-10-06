from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models as m
from app.github.conclusions import healthy_filter
from app.db.session import get_db
from app.schemas.workspace import HealthOut, RepoOut, SessionOut

router = APIRouter(prefix="/api/repos", tags=["repos"])


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


@router.get("", response_model=list[RepoOut])
def list_repos(db: Session = Depends(get_db)) -> list[RepoOut]:
    repos = db.scalars(select(m.Repo).order_by(m.Repo.id)).all()
    return [
        RepoOut(id=r.id, owner=r.owner, name=r.name, full_name=r.full_name,
                default_branch=r.default_branch, is_github=r.is_github)
        for r in repos
    ]


@router.get("/{repo_id}/health", response_model=HealthOut)
def repo_health(repo_id: int, db: Session = Depends(get_db)) -> HealthOut:
    _require_repo(db, repo_id)
    return HealthOut(**health_of(db, repo_id))


@router.get("/{repo_id}/sessions", response_model=list[SessionOut])
def list_sessions(repo_id: int, db: Session = Depends(get_db)) -> list[SessionOut]:
    _require_repo(db, repo_id)
    rows = db.scalars(select(m.Session).where(m.Session.repo_id == repo_id)
                      .order_by(m.Session.id)).all()
    return [SessionOut(id=s.id, title=s.title, repo_id=s.repo_id) for s in rows]