"""MCP 客户端:两种 transport。

- `inprocess`:同一进程内直连示例工具。默认。保证 Demo 离线可跑、单测稳定。
- `stdio`:**真实 MCP** —— 拉起服务端子进程,走官方 SDK 的 JSON-RPC over stdio,
  完成 initialize 握手后再 list_tools / call_tool。

外部工具统一加 `mcp__<server>__<tool>` 前缀注册,避免和内置工具重名。

**一个刻意的取舍**:stdio 模式下**每次调用都新起一个子进程**,而不是维持长连接。
理由是生命周期管理(跨事件循环持有子进程、异常断开重连)在这个 Demo 里是纯粹的复杂度,
而 MCP 工具调用频率很低。代价是每次调用有几十到几百毫秒的进程启动开销 ——
真要上生产,应该换成常驻连接池,这一点写在注释里而不是藏着。
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass

from app.config import settings
from app.mcp.servers import local_tools

logger = logging.getLogger(__name__)


@dataclass
class MCPServerTool:
    name: str
    description: str
    parameters: dict
    server: str


def _extract_payload(result: object) -> dict:
    """把 MCP 的 CallToolResult 转回普通 dict。

    服务端返回的是 content 列表,文本项里装的是 JSON 字符串。
    """
    if getattr(result, "isError", False):
        raise RuntimeError(f"MCP 工具执行失败:{result}")

    texts = [
        item.text for item in getattr(result, "content", [])
        if getattr(item, "type", "") == "text" and isinstance(getattr(item, "text", None), str)
    ]
    if not texts:
        # 结构化输出(新协议)优先
        structured = getattr(result, "structuredContent", None)
        return structured if isinstance(structured, dict) else {}

    raw = texts[0]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}
    return parsed if isinstance(parsed, dict) else {"text": parsed}


class MCPClient:
    def __init__(self, transport: str | None = None, server: str = "local",
                 command: str | None = None, args: list[str] | None = None) -> None:
        self.transport = transport or settings.mcp_transport
        self.server = server
        self.command = command or settings.mcp_server_command
        self.args = args if args is not None else settings.mcp_server_args_list

    @classmethod
    def transport_for(cls, name: str) -> "MCPClient":
        return cls(transport=name)

    # ------------------------------------------------------------------ stdio

    def _server_params(self):  # noqa: ANN202
        from mcp import StdioServerParameters

        return StdioServerParameters(
            command=self.command or sys.executable,
            args=list(self.args),
            env=None,
        )

    async def _with_session(self, action):  # noqa: ANN001, ANN202
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(self._server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)

    # ------------------------------------------------------------------ 对外

    async def list_tools(self) -> list[MCPServerTool]:
        if self.transport == "inprocess":
            return [
                MCPServerTool(
                    name=f"mcp__{self.server}__{name}",
                    description=description,
                    parameters=parameters,
                    server=self.server,
                )
                for name, (description, _, parameters) in local_tools.TOOLS.items()
            ]

        if self.transport != "stdio":
            raise NotImplementedError(f"未知的 MCP transport:{self.transport!r}")

        async def action(session):  # noqa: ANN001, ANN202
            return await session.list_tools()

        listed = await self._with_session(action)
        return [
            MCPServerTool(
                name=f"mcp__{self.server}__{tool.name}",
                description=tool.description or "",
                parameters=getattr(tool, "inputSchema", None) or {"type": "object"},
                server=self.server,
            )
            for tool in listed.tools
        ]

    async def call_tool(self, name: str, args: dict) -> dict:
        prefix = f"mcp__{self.server}__"
        if not name.startswith(prefix):
            raise ValueError(f"工具 {name!r} 不属于 server {self.server!r}")
        bare = name[len(prefix):]

        if self.transport == "inprocess":
            entry = local_tools.TOOLS.get(bare)
            if entry is None:
                raise KeyError(f"MCP 服务端没有工具 {bare!r}")
            _, handler, _ = entry
            return handler(args or {})

        if self.transport != "stdio":
            raise NotImplementedError(f"未知的 MCP transport:{self.transport!r}")

        async def action(session):  # noqa: ANN001, ANN202
            return await session.call_tool(bare, args or {})

        return _extract_payload(await self._with_session(action))