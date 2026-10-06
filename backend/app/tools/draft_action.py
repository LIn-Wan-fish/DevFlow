"""唯一带写意图的工具 —— 但它只生成草稿,不执行。

模型能拿到的最大权限就是这里:产出一条 pending 状态的草稿等人确认。
"""

from __future__ import annotations

from app.safety import drafts as draft_store
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def draft_action(
    ctx: ToolContext,
    action: str = "comment_on_issue",
    target: str = "",
    body: str = "",
    labels: list[str] | None = None,
    **_: object,
) -> ToolResult:
    payload: dict = {}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = labels

    draft = draft_store.create(
        ctx.db,
        repo_id=ctx.repo_id,
        run_id=ctx.run_id,
        action=action,
        target=target,
        payload=payload,
        role=ctx.role,
    )

    return ToolResult(
        tool="draft_action",
        summary=(
            f"已生成写操作草稿 #{draft.id}({action} → {target}),"
            f"风险等级 {draft.risk_level},**等待人工确认后才执行**。"
        ),
        data={
            "draft_id": draft.id,
            "action": draft.action,
            "target": draft.target,
            "risk_level": draft.risk_level,
            "status": draft.status,
            "preview": draft.preview,
        },
        evidence_refs=[target] if target else [],
    )


register(ToolSpec(
    name="draft_action",
    description=(
        "为写操作(评论 / 加标签 / 关闭或重开 Issue)生成草稿。"
        "这是唯一涉及写操作的工具,且只生成草稿,不执行 —— 执行必须由人工确认。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["comment_on_issue", "add_labels", "close_issue", "reopen_issue"],
                "description": "写操作类型",
            },
            "target": {"type": "string", "description": "目标,例如 issue#3"},
            "body": {"type": "string", "description": "评论内容(comment_on_issue 时需要)"},
            "labels": {"type": "array", "items": {"type": "string"}, "description": "要添加的标签"},
        },
        "required": ["action", "target"],
    },
    handler=draft_action,
    is_write=True,
))