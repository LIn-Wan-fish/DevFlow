from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.issue import ISSUE_SYSTEM
from app.core.prompts.roles import AgentRole
from app.db import models as m
from app.schemas.issue import IssueTriage


class IssueAgent(SpecialistAgent):
    role = AgentRole.ISSUE
    schema = IssueTriage

    @property
    def system_prompt(self) -> str:
        return ISSUE_SYSTEM

    def gather_evidence(self, db: Session, *, repo_id: int, number: int, **_: object) -> dict:
        issue = db.scalar(
            select(m.Issue).where(m.Issue.repo_id == repo_id, m.Issue.number == number)
        )
        if issue is None:
            return {"number": number, "missing": True, "title": "", "body": "", "labels": []}
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "labels": issue.labels,
            "state": issue.state,
            "author": issue.author,
            "assignee": issue.assignee,
            "group": issue.group,
        }