"""进入多 Agent 工作流。

ChatAgent 只判断「需不需要综合判断」,真正拆解与调度交给工作流。
"""

from __future__ import annotations

from app.agents.orchestrator import run_workflow as execute_workflow
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def run_workflow(ctx: ToolContext, question: str = "", **_: object) -> ToolResult:
    outcome = await execute_workflow(
        ctx.db,
        repo_id=ctx.repo_id,
        question=question,
        emit=ctx.emit,
        cancel=ctx.cancel,
    )
    return ToolResult(
        tool="run_workflow",
        summary=outcome.answer,
        data={
            "conclusion": outcome.answer,
            "conflicts": outcome.conflicts,
            "gaps": outcome.gaps,
            "replan_count": outcome.replan_count,
            # 完整任务信息带回 API 层,用于落 WorkflowRun / TaskRun 轨迹
            "tasks": [
                {
                    "task_key": t["task_key"],
                    "agent": t["agent"],
                    "title": t.get("title", ""),
                    "depends_on": t.get("depends_on") or [],
                    "status": t["status"],
                    "output": t.get("output") or {},
                    "error": t.get("error"),
                }
                for t in outcome.tasks
            ],
        },
        evidence_refs=["workflow"],
    )


register(ToolSpec(
    name="run_workflow",
    description=(
        "对复杂研发问题启动多 Agent 协作:拆解任务、并行分析、交叉检查证据冲突、汇总结论。"
        "当问题同时涉及 Issue、PR、CI,或需要判断版本能否发布时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string", "description": "要综合分析的研发问题"}},
        "required": ["question"],
    },
    handler=run_workflow,
))