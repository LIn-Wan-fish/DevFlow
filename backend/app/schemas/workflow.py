from enum import StrEnum

from pydantic import BaseModel, Field


class WorkflowAgent(StrEnum):
    ISSUE = "issue_agent"
    PR_REVIEW = "pr_review_agent"
    CI_DEBUG = "ci_debug_agent"
    SAFETY = "safety_agent"
    SYNTHESIS = "synthesis"


class TaskSpec(BaseModel):
    task_key: str = Field(description="任务唯一键")
    agent: WorkflowAgent = Field(description="执行者")
    title: str = Field(description="任务标题")
    depends_on: list[str] = Field(default_factory=list, description="依赖的 task_key")
    number: int | None = Field(default=None, description="目标编号(PR/CI/Issue 编号)")
    action: str | None = Field(default=None, description="仅 safety_agent 使用:待评估的写操作名")
    target: str | None = Field(default=None, description="仅 safety_agent 使用:写操作目标")


class Plan(BaseModel):
    tasks: list[TaskSpec] = Field(description="拆解出的任务,依赖必须构成有向无环图")


class Observation(BaseModel):
    gaps: list[str] = Field(default_factory=list, description="证据缺口")
    conflicts: list[str] = Field(default_factory=list, description="结论冲突")
    safety: dict = Field(default_factory=dict, description="安全条件")


class Synthesis(BaseModel):
    conclusion: str = Field(description="明确的工程结论,不要写「视情况而定」")
    evidence: list[str] = Field(description="支撑依据,标明来自哪个 Agent")
    next_steps: list[str] = Field(description="具体到人可以做的一步")
    confidence: str = Field(description="high / medium / low")