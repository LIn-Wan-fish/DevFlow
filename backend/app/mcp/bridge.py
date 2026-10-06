"""把 MCP 服务端的工具**注册进工具表**。

为什么需要这一步:在此之前 MCP 只是 `/api/mcp/tools` 里能列出来的一段展示 ——
Agent 根本调不到它们。章节 10 讲的是「扩展 ChatAgent 的能力」,
所谓扩展,落到代码上就是**这些工具要出现在 Agent 的工具表里**。

注册出来的名字带 `mcp__<server>__<tool>` 前缀,不会和内置工具撞名。
工具发现失败时只记警告不抛异常:外部服务连不上不该让整个应用起不来。
"""

from __future__ import annotations

import logging
from typing import Any

from app.mcp.client import MCPClient, MCPServerTool
from app.tools.registry import REGISTRY, ToolContext, ToolResult, ToolSpec, register

logger = logging.getLogger(__name__)

DEFAULT_SERVER_NAME = "local"


def _summarize(data: dict[str, Any]) -> str:
    """把工具返回的 dict 压成一行摘要,给运行轨迹和模型看。"""
    if not data:
        return "MCP 工具返回空结果"
    parts = [f"{key}={value}" for key, value in list(data.items())[:4]]
    return "MCP 工具返回:" + ", ".join(str(p) for p in parts)


def _make_handler(client: MCPClient, tool_name: str):  # noqa: ANN202
    async def handler(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        data = await client.call_tool(tool_name, kwargs)
        return ToolResult(
            tool=tool_name,
            summary=_summarize(data),
            data=data,
            evidence_refs=[f"mcp:{tool_name}"],
        )

    return handler


async def install_mcp_tools(server_name: str = DEFAULT_SERVER_NAME) -> list[MCPServerTool]:
    """发现并注册 MCP 工具。返回被注册的那些(已注册过的会跳过)。"""
    client = MCPClient(server=server_name)
    try:
        tools = await client.list_tools()
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP 工具发现失败(transport=%s),跳过外部工具:%s",
                       client.transport, exc)
        return []

    installed: list[MCPServerTool] = []
    for tool in tools:
        if tool.name in REGISTRY:
            continue
        register(ToolSpec(
            name=tool.name,
            description=tool.description or "外部 MCP 工具",
            parameters=tool.parameters or {"type": "object", "properties": {}},
            handler=_make_handler(client, tool.name),
            # 外部工具一律按只读对待:写操作必须走内置的草稿闸门,
            # 不能让一个外部注册的工具绕过人工确认。
            is_write=False,
        ))
        installed.append(tool)

    logger.info("已接入 %s 个 MCP 工具(transport=%s):%s",
                len(installed), client.transport, [t.name for t in installed])
    return installed