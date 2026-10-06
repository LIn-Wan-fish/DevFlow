from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import SpecialistAgent
from app.core.prompts.roles import AgentRole
from app.core.prompts.safety import SAFETY_SYSTEM
from app.db import models as m
from app.db.models import DraftStatus
from app.safety.policy import WRITE_ACTIONS, risk_level
from app.schemas.safety import SafetyAssessment, SafetyLevel


class SafetyAgent(SpecialistAgent):
    role = AgentRole.SAFETY
    schema = SafetyAssessment

    @property
    def system_prompt(self) -> str:
        return SAFETY_SYSTEM

    def gather_evidence(
        self, db: Session, *, action: str = "", target: str = "", **_: object
    ) -> dict:
        return {
            "action": action,
            "target": target,
            "in_whitelist": action in WRITE_ACTIONS,
            "policy_risk_level": risk_level(action) if action else "low",
            "requires_human_confirmation": True,
        }

    def check_repo(self, db: Session, repo_id: int) -> SafetyAssessment:
        """发布前的**仓库级**安全与合规检查(确定性,不调用模型)。

        与 `gather_evidence` 的分工:

        - `gather_evidence` 评的是「某个具体写操作能不能做」
        - `check_repo` 扫的是「整个仓库当前有没有悬着的风险」

        为什么需要它:真实模型在被问到「这个版本能不能发布」时,
        会规划出一个 `safety_agent` 任务(标题通常就是「发布前安全与合规风险检查」),
        而调度器原先只认识 issue/pr/ci 三种执行者,**遇到 safety 直接抛 ValueError**,
        该维度被整个判死 —— 这条路径在快照数据下从没被触发过。
        """
        reasons: list[str] = []

        pending = db.scalars(
            select(m.ActionDraft).where(
                m.ActionDraft.repo_id == repo_id,
                m.ActionDraft.status == DraftStatus.PENDING.value,
            )
        ).all()
        if pending:
            listing = ", ".join(f"#{d.id} {d.action}→{d.target}" for d in pending[:5])
            reasons.append(
                f"有 {len(pending)} 条写操作草稿尚未确认({listing});"
                "确认前这些写操作都没有真正执行,发布前应清空或明确放弃"
            )

        denied = db.scalars(
            select(m.AuditLog).where(m.AuditLog.result == "denied")
        ).all()
        if denied:
            actors = ", ".join(sorted({d.actor_role for d in denied if d.actor_role}))
            reasons.append(
                f"审计中存在 {len(denied)} 次被拦下的越权尝试"
                + (f"(角色:{actors})" if actors else "")
                + ";需确认是误操作还是探测"
            )

        risky = db.scalars(
            select(m.PrFile)
            .join(m.PullRequest, m.PrFile.pr_id == m.PullRequest.id)
            .where(m.PullRequest.repo_id == repo_id, m.PrFile.is_high_risk.is_(True))
        ).all()
        if risky:
            paths = ", ".join(sorted({f.path for f in risky})[:5])
            reasons.append(f"改动触及高风险路径({paths}),必须人工复核后再决定发布")

        if not reasons:
            reasons.append("无待确认写操作、无越权记录、未触及高风险路径")

        if denied:
            level = SafetyLevel.HIGH
        elif pending or risky:
            level = SafetyLevel.MEDIUM
        else:
            level = SafetyLevel.LOW

        return SafetyAssessment(
            level=level,
            reasons=reasons,
            # 这些动作**不允许**直接被模型执行,只能出草稿并等人工确认
            forbidden_actions=sorted(WRITE_ACTIONS),
            draft_only=True,
        )