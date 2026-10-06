from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.ci_debug import CI_DEBUG_SYSTEM
from app.core.prompts.roles import AgentRole
from app.db import models as m
from app.schemas.ci import CIDebug

MAX_LOG_CHARS = 20000


class CIDebugAgent(SpecialistAgent):
    role = AgentRole.CI_DEBUG
    schema = CIDebug

    @property
    def system_prompt(self) -> str:
        return CI_DEBUG_SYSTEM

    def gather_evidence(self, db: Session, *, repo_id: int, number: int, **_: object) -> dict:
        run = db.scalar(
            select(m.CiRun).where(m.CiRun.repo_id == repo_id, m.CiRun.number == number)
        )
        if run is None:
            # 找不到就明说,不要拿别的 CI 的日志顶上
            return {"number": number, "missing": True, "log": ""}
        return {
            "number": run.number,
            "workflow": run.workflow,
            "branch": run.branch,
            "status": run.status,
            "conclusion": run.conclusion,
            "commit_sha": run.commit_sha,
            "commit_message": run.commit_message,
            "log": _read_log(run.log_path),
        }


def _read_log(path: str) -> str:
    if not path:
        return ""
    file = Path(path)
    if not file.exists():
        return ""
    return file.read_text(encoding="utf-8", errors="replace")[:MAX_LOG_CHARS]