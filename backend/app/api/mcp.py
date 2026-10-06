"""MCP 外部工具的查看。

`/api/mcp/tools` 会**同时报告每个工具是否真的注册进了运行中的工具表** ——
只列出服务端有什么是不够的:章节 10 讲的是「扩展 ChatAgent 的能力」,
一个列得出来但 Agent 调不到的工具,等于没接。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.mcp.client import MCPClient
from app.tools.registry import REGISTRY

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools")
async def list_tools() -> dict:
    client = MCPClient()
    tools = await client.list_tools()
    return {
        "transport": client.transport,
        "server": client.server,
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                # 关键字段:服务端有这个工具 ≠ Agent 调得到它
                "registered": t.name in REGISTRY,
            }
            for t in tools
        ],
        "registered_count": sum(1 for t in tools if t.name in REGISTRY),
    }