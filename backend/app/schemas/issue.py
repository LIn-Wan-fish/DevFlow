from enum import StrEnum

from pydantic import BaseModel, Field


class IssueCategory(StrEnum):
    BUG = "Bug"
    FEATURE = "Feature"
    QUESTION = "Question"
    DOCS = "Docs"
    CHORE = "Chore"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Complexity(StrEnum):
    S = "S"
    M = "M"
    L = "L"


class IssueTriage(BaseModel):
    """Issue 分诊结果。IssueAgent 的输出契约。"""

    category: IssueCategory = Field(description="问题分类")
    priority: Priority = Field(description="优先级,P0 最高")
    complexity: Complexity = Field(description="实现复杂度评估")
    recommended_assignee: str = Field(description="推荐负责人;无法判断时写「未分配」")
    action_items: list[str] = Field(description="可执行的行动项,至少一条")
    rationale: str = Field(description="判断依据,必须引用 Issue 里的具体信息")