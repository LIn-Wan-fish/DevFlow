from enum import StrEnum

from pydantic import BaseModel, Field


class PRDecision(StrEnum):
    MERGE = "merge"
    HOLD = "hold"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PRReview(BaseModel):
    """PR 审查结果。PRReviewAgent 的输出契约。"""

    decision: PRDecision = Field(description="建议合入(merge)或暂缓(hold)")
    risk_level: RiskLevel = Field(description="改动风险等级")
    high_risk_paths: list[str] = Field(description="命中的高风险路径")
    findings: list[str] = Field(description="逐条审查发现")
    missing_checks: list[str] = Field(description="上线前还缺哪些检查/验证")
    rationale: str = Field(description="结论依据")