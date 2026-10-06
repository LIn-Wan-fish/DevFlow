from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.pr_review import PR_REVIEW_SYSTEM
from app.core.prompts.roles import AgentRole
from app.db import models as m
from app.schemas.pr import PRReview


class PRReviewAgent(SpecialistAgent):
    role = AgentRole.PR_REVIEW
    schema = PRReview

    @property
    def system_prompt(self) -> str:
        return PR_REVIEW_SYSTEM

    def gather_evidence(self, db: Session, *, repo_id: int, number: int, **_: object) -> dict:
        pr = db.scalar(
            select(m.PullRequest).where(
                m.PullRequest.repo_id == repo_id, m.PullRequest.number == number
            )
        )
        if pr is None:
            return {"number": number, "missing": True, "files": [], "reviews": []}
        # 刻意不返回 CI 结论:PR Agent 只审改动本身,
        # CI 是否阻塞归 CI Agent。两者的分歧正是 Observer 要抓的冲突。
        return {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "head_ref": pr.head_ref,
            "base_ref": pr.base_ref,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "changed_files": pr.changed_files,
            "related_issues": pr.related_issues,
            "reviews": pr.reviews,
            "files": [
                {
                    "path": f.path,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch_summary": f.patch_summary,
                    "is_high_risk": f.is_high_risk,
                }
                for f in pr.files
            ],
        }