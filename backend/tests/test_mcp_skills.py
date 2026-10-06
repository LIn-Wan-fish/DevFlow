"""Task 16 验收:MCP 扩展通道 + Skill Runtime 入参校验。"""

import pytest

from app.mcp.client import MCPClient
from app.skills.runtime import SkillInputError, SkillRuntime

SKILL_PATH = "app/skills/skills/repo_health_report.yaml"


async def test_mcp_列出外部工具并带命名空间():
    tools = await MCPClient.transport_for("inprocess").list_tools()
    assert tools
    assert all(t.name.startswith("mcp__") for t in tools)


async def test_mcp_调用外部工具返回结构化结果():
    result = await MCPClient.transport_for("inprocess").call_tool("mcp__local__echo", {"text": "hi"})
    assert result["echo"] == "hi"


async def test_mcp_入参缺失时报错而不是猜():
    from app.mcp.servers.local_tools import ToolInputError

    with pytest.raises(ToolInputError):
        await MCPClient().call_tool("mcp__local__echo", {})


async def test_mcp_跨_server_调用被拒():
    with pytest.raises(ValueError):
        await MCPClient(server="local").call_tool("mcp__other__echo", {"text": "x"})


def test_skill_文件可解析且步骤非空():
    skill = SkillRuntime().load(SKILL_PATH)
    assert skill.name == "repo_health_report"
    assert skill.steps


def test_skill_入参校验拒绝缺字段():
    runtime = SkillRuntime()
    skill = runtime.load(SKILL_PATH)
    with pytest.raises(SkillInputError):
        runtime.run(skill, {}, executor=lambda tool, args: {"ok": True})


def test_skill_按声明顺序执行步骤():
    runtime = SkillRuntime()
    skill = runtime.load(SKILL_PATH)
    calls = []

    def executor(tool, args):  # noqa: ANN001
        calls.append((tool, args))
        return {"ok": True}

    result = runtime.run(skill, {"repo_id": 1}, executor=executor)
    assert result["steps_executed"] == len(skill.steps)
    assert [c[0] for c in calls] == [s["tool"] for s in skill.steps]
    assert calls[0][1]["repo_id"] == 1, "占位符必须被真实入参替换"


def test_skill_缺文件时报格式错误():
    from app.skills.runtime import SkillFormatError

    with pytest.raises(SkillFormatError):
        SkillRuntime().load("app/skills/skills/does_not_exist.yaml")