from app.agents.pr_review_agent import PRReviewAgent
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def review_pr(ctx: ToolContext, number: int | None = None, **_: object) -> ToolResult:
    if number is None:
        return ToolResult(tool="review_pr", summary="未指定 PR 编号,无法审查。", data={}, empty=True)
    review = await PRReviewAgent().run(ctx.db, repo_id=ctx.repo_id, number=int(number))
    data = review.model_dump(mode="json")
    summary = (
        f"PR #{number} 建议 {review.decision.value}(风险 {review.risk_level.value}),"
        f"命中高风险路径 {len(review.high_risk_paths)} 处,"
        f"待补检查 {len(review.missing_checks)} 项。"
    )
    return ToolResult(tool="review_pr", summary=summary, data=data,
                      evidence_refs=[f"pr#{number}", *review.high_risk_paths])


register(ToolSpec(
    name="review_pr",
    description="审查一个 PR 的改动:是否建议合入、风险等级、高风险路径与缺失检查。",
    parameters={
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "PR 编号"}},
        "required": ["number"],
    },
    handler=review_pr,
))