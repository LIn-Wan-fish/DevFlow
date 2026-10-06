from app.agents.safety_agent import SafetyAgent
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def safety_check(
    ctx: ToolContext, action: str = "", target: str = "", **_: object
) -> ToolResult:
    assessment = await SafetyAgent().run(ctx.db, action=action, target=target)
    data = assessment.model_dump(mode="json")
    summary = (
        f"动作 {action or '(未指定)'} 的安全等级为 {assessment.level.value},"
        f"必须走草稿 + 人工确认后才能执行。"
    )
    return ToolResult(tool="safety_check", summary=summary, data=data)


register(ToolSpec(
    name="safety_check",
    description="评估一个写操作的风险等级与前置条件(只评估,不执行)。",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "拟执行的动作"},
            "target": {"type": "string", "description": "目标,例如 issue#3"},
        },
        "required": ["action"],
    },
    handler=safety_check,
))