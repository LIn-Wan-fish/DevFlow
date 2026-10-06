"""最小 MCP 客户端。

两种 transport:
- inprocess:进程内直连,默认。保证 Demo 离线可跑、单测稳定。
- stdio:留给真实 MCP server(JSON-RPC over stdio),此处仅留接口。

外部工具统一加 mcp__<server>__<tool> 前缀注册,避免和内置工具重名。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.mcp.servers import local_tools


@dataclass
class MCPServerTool:
    name: str
    description: str
    parameters: dict
    server: str


class MCPClient:
    def __init__(self, transport: str = "inprocess", server: str = "local") -> None:
        self.transport = transport
        self.server = server

    @classmethod
    def transport_for(cls, name: str) -> "MCPClient":
        return cls(transport=name)

    async def list_tools(self) -> list[MCPServerTool]:
        if self.transport != "inprocess":
            # 真实 stdio transport 需要拉起子进程并走 JSON-RPC 握手。
            # Demo 不实现它 —— 留空比假装实现更诚实。
            raise NotImplementedError("仅实现 inprocess transport")
        return [
            MCPServerTool(
                name=f"mcp__{self.server}__{name}",
                description=description,
                parameters=parameters,
                server=self.server,
            )
            for name, (description, _, parameters) in local_tools.TOOLS.items()
        ]

    async def call_tool(self, name: str, args: dict) -> dict:
        prefix = f"mcp__{self.server}__"
        if not name.startswith(prefix):
            raise ValueError(f"工具 {name!r} 不属于 server {self.server!r}")
        bare = name[len(prefix):]
        entry = local_tools.TOOLS.get(bare)
        if entry is None:
            raise KeyError(f"MCP 服务端没有工具 {bare!r}")
        _, handler, _ = entry
        return handler(args or {})