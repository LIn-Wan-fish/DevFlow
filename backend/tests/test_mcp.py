"""MCP:真实 stdio transport、工具注册、服务端语义。"""

from __future__ import annotations

import pytest

from app.mcp.bridge import install_mcp_tools
from app.mcp.client import MCPClient
from app.mcp.servers import local_tools
from app.tools.registry import REGISTRY


# --------------------------------------------------------------------------- inprocess


async def test_inprocess_列出示例工具():
    tools = await MCPClient(transport="inprocess").list_tools()
    names = {t.name for t in tools}
    # 进程内示例工具与 stdio 服务端的工具集**故意不同**:前者只用来验证链路,后者是真实能力\n    assert names == {"mcp__local__echo", "mcp__local__now", "mcp__local__word_count"}


async def test_前缀不对的工具会被拒绝():
    """外部工具统一加前缀,避免和内置工具撞名 —— 调用时也要守住这条。"""
    client = MCPClient(transport="inprocess")
    with pytest.raises(ValueError):
        await client.call_tool("repo_health", {})


async def test_inprocess_调用并校验入参():
    client = MCPClient(transport="inprocess")
    assert await client.call_tool("mcp__local__echo", {"text": "hi"}) == {"echo": "hi"}
    with pytest.raises(local_tools.ToolInputError):
        await client.call_tool("mcp__local__word_count", {})  # 缺必填 text


def test_未知_transport_明确报错而不是静默降级():
    import asyncio

    client = MCPClient(transport="http")
    with pytest.raises(NotImplementedError):
        asyncio.run(client.list_tools())


# --------------------------------------------------------------------------- 真实 stdio


async def test_stdio_能拉起真实服务端并列出工具():
    """真 MCP:子进程 + JSON-RPC over stdio + initialize 握手。"""
    tools = await MCPClient(transport="stdio").list_tools()
    names = {t.name for t in tools}
    assert {"mcp__local__now", "mcp__local__count_text",
            "mcp__local__compare_semver"} <= names


async def test_stdio_真实调用返回结构化结果():
    client = MCPClient(transport="stdio")
    # 预发布版 < 正式版 —— 这条规则在判断「能不能发布」时真的会用到
    out = await client.call_tool("mcp__local__compare_semver",
                                 {"left": "1.2.3-rc.1", "right": "1.2.3"})
    assert out["result"] == -1
    assert "早于" in out["conclusion"]

    counted = await client.call_tool("mcp__local__count_text", {"text": "a b\nc"})
    assert counted["chars"] == 5 and counted["lines"] == 2


# --------------------------------------------------------------------------- 语义


@pytest.mark.parametrize("left,right,expected", [
    ("1.2.3", "1.2.3", 0),
    ("1.2.3", "1.2.4", -1),
    ("2.0.0", "1.9.9", 1),
    ("1.2.3-rc.1", "1.2.3", -1),   # 预发布 < 正式
    ("1.2.3", "1.2.3-rc.1", 1),
])
def test_版本比较语义(left, right, expected):
    from app.mcp.servers.demo_server import compare_semver

    assert compare_semver(left, right)["result"] == expected


def test_非法版本号明确报错():
    from app.mcp.servers.demo_server import compare_semver

    with pytest.raises(ValueError):
        compare_semver("v1.2", "1.2.3")


# --------------------------------------------------------------------------- 注册进工具表


async def test_接入后_Agent_真的调得到(monkeypatch):
    """回归:在此之前 MCP 只是 /api/mcp/tools 里能列出来的展示,Agent 根本调不到。

    章节 10 讲的是「扩展 ChatAgent 的能力」—— 所谓扩展,落到代码上就是
    这些工具必须出现在 Agent 的工具表里。
    """
    for name in [n for n in REGISTRY if n.startswith("mcp__")]:
        REGISTRY.pop(name)

    installed = await install_mcp_tools()
    # 默认 inprocess transport => 3 个示例工具
    assert len(installed) == 3
    for tool in installed:
        assert tool.name in REGISTRY, "注册了才算接上"

    # 再调一次不应该重复注册
    assert await install_mcp_tools() == []


async def test_外部工具一律按只读对待():
    """写操作必须走内置的草稿闸门,不能让外部注册的工具绕过人工确认。"""
    await install_mcp_tools()
    for name in [n for n in REGISTRY if n.startswith("mcp__")]:
        assert REGISTRY[name].is_write is False


async def test_服务端连不上时不带崩应用(monkeypatch):
    """外部服务挂了,应用必须照常起来 —— 只记警告,不抛异常。"""
    from app.config import settings

    monkeypatch.setattr(settings, "mcp_server_args", "-m 不存在的模块")
    installed = await install_mcp_tools()
    # 允许为空(发现失败),但绝不能抛异常把 lifespan 带崩
    assert installed == [] or isinstance(installed, list)