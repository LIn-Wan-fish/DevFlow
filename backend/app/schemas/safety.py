from enum import StrEnum

from pydantic import BaseModel, Field


class SafetyLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SafetyAssessment(BaseModel):
    """安全风险评估。SafetyAgent 的输出契约。"""

    level: SafetyLevel = Field(description="整体风险等级")
    reasons: list[str] = Field(description="判断理由")
    forbidden_actions: list[str] = Field(description="本场景下被禁止的动作")
    draft_only: bool = Field(default=True, description="是否必须走草稿+人工确认,恒为 true")