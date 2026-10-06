from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.roles import AgentRole
from app.core.prompts.workflow import OBSERVER_SYSTEM
from app.core.workflow_rules import collect_facts, detect_conflicts, detect_gaps
from app.schemas.workflow import Observation


class ObserverAgent(SpecialistAgent):
    role = AgentRole.OBSERVER
    schema = Observation

    @property
    def system_prompt(self) -> str:
        return OBSERVER_SYSTEM

    def gather_evidence(
        self,
        db: Session,
        *,
        question: str = "",
        results: list[dict] | None = None,
        tasks: list[dict] | None = None,
        degraded: list[str] | None = None,
        **_: object,
    ) -> dict:
        results = results or []
        return {
            "question": question,
            "results": results,
            "tasks": tasks or [],
            "degraded": degraded or [],
            # 事实信号一并给模型,让它的补充说明和硬规则基于同一份数据
            "facts": collect_facts(results),
        }


def hard_rules(results: list[dict], tasks: list[dict], degraded: list[str]) -> Observation:
    """不依赖模型的冲突/缺口判定。

    模型只负责补充说明;冲突必须由规则先算出来 ——
    否则「PR 说可合、CI 说阻塞」很容易被模型和成一个「建议进一步确认」。
    """
    facts = collect_facts(results)
    return Observation(
        gaps=detect_gaps(facts, tasks, degraded),
        conflicts=detect_conflicts(facts),
        safety={"draft_only": True, "write_actions_require_confirmation": True},
    )