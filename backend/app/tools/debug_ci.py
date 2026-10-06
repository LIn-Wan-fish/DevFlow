from app.agents.ci_debug_agent import CIDebugAgent
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def debug_ci(ctx: ToolContext, number: int | None = None, **_: object) -> ToolResult:
    if number is None:
        return ToolResult(tool="debug_ci", summary="未指定 CI 编号,无法排障。", data={}, empty=True)
    debug = await CIDebugAgent().run(ctx.db, repo_id=ctx.repo_id, number=int(number))
    data = debug.model_dump(mode="json")
    # summary 直接用根因:它包含日志里的原始报错信息(如 401),
    # 是最终回答里最关键的那句话。
    return ToolResult(
        tool="debug_ci",
        summary=f"CI #{number} 根因:{debug.root_cause}",
        data=data,
        evidence_refs=[f"ci#{number}", *debug.related_files],
    )


register(ToolSpec(
    name="debug_ci",
    description="分析一次失败的 CI:从日志定位根因、摘录关键错误块并给出修复步骤。",
    parameters={
        "type": "object",
        "properties": {"number": {"type": "integer", "description": "CI 运行编号"}},
        "required": ["number"],
    },
    handler=debug_ci,
))