from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.roles import AgentRole
from app.core.prompts.workflow import SYNTHESIS_SYSTEM
from app.core.workflow_rules import collect_facts
from app.schemas.workflow import Synthesis


class SynthesisAgent(SpecialistAgent):
    role = AgentRole.SYNTHESIS
    schema = Synthesis

    @property
    def system_prompt(self) -> str:
        return SYNTHESIS_SYSTEM

    def gather_evidence(
        self,
        db: Session,
        *,
        question: str = "",
        results: list[dict] | None = None,
        conflicts: list[str] | None = None,
        gaps: list[str] | None = None,
        **_: object,
    ) -> dict:
        results = results or []
        return {
            "question": question,
            "results": results,
            "conflicts": conflicts or [],
            "gaps": gaps or [],
            "facts": collect_facts(results),
        }