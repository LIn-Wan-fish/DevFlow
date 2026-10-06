from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.roles import AgentRole
from app.core.prompts.workflow import PLANNER_SYSTEM
from app.schemas.workflow import Plan


class PlannerAgent(SpecialistAgent):
    role = AgentRole.PLANNER
    schema = Plan

    @property
    def system_prompt(self) -> str:
        return PLANNER_SYSTEM

    def gather_evidence(
        self, db: Session, *, question: str = "", targets: dict | None = None, **_: object
    ) -> dict:
        return {"question": question, "targets": targets or {}}