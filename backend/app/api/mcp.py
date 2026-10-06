from fastapi import APIRouter

from app.mcp.client import MCPClient

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools")
async def list_tools() -> dict:
    """列出已接入的外部工具。用来证明扩展通道是通的,而不是嘴上说说。"""
    client = MCPClient()
    tools = await client.list_tools()
    return {
        "transport": client.transport,
        "server": client.server,
        "tools": [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in tools
        ],
    }