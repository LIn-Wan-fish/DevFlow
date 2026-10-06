from app.agents.issue_agent import IssueAgent
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def analyze_issue(ctx: ToolContext, number: int | None = None, **_: object) -> ToolResult:
    if number is None:
        return ToolResult(tool="analyze_issue", summary="未指定 Issue 编号,无法分析。",
                          data={}, empty=True)
    triage = await IssueAgent().run(ctx.db, repo_id=ctx.repo_id, number=int(number))
    data = triage.model_dump(mode="json")
    summary = (
        f"Issue #{number} 分类 {triage.category.value}、优先级 {triage.priority.value}、"
        f"复杂度 {triage.complexity.value},建议负责人 {triage.recommended_assignee}。"
    )
    return ToolResult(tool="analyze_issue", summary=summary, data=data,
                      evidence_refs=[f"issue#{number}"])


register(ToolSpec(
    name="analyze_issue",
    description="分析一个 Issue:分类、优先级、复杂度、推荐负责人与行动项。",
    parameters={
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "Issue 编号"}},
        "required": ["number"],
    },
    handler=analyze_issue,
))