"""Skill 注册进工具表:从「声明」到「Agent 真的调得到」。"""

from __future__ import annotations

import pytest

from app.skills.bridge import (_exposed_parameters, _is_write_skill, install_skill_tools,
                               load_skills)
from app.skills.runtime import SkillRuntime
from app.tools.registry import REGISTRY, ToolContext, ToolSpec, execute, register


@pytest.fixture(autouse=True)
def _clean_skill_tools():
    """每个用例前后都清掉技能工具,避免相互污染。"""
    for name in [n for n in REGISTRY if n.startswith("skill__")]:
        REGISTRY.pop(name)
    yield
    for name in [n for n in REGISTRY if n.startswith("skill__")]:
        REGISTRY.pop(name)


def test_技能库非空且都能解析():
    skills = load_skills()
    names = {s.name for s in skills}
    assert {"repo_health_report", "ci_failure_triage",
            "issue_intake", "release_readiness"} <= names
    for skill in skills:
        assert skill.steps, f"{skill.name} 必须有步骤"


def test_接入后_Agent_真的调得到():
    """回归:技能原先只是 /api/skills 里列得出来、点得动 —— Agent 调不到。

    章节 10.2 的标题就是「MCP 与 Skill 怎么进入 ChatAgent」。
    """
    installed = install_skill_tools()
    assert len(installed) >= 4
    for name in installed:
        assert name in REGISTRY
    # 重复接入不该重复注册
    assert install_skill_tools() == []


def test_repo_id_不暴露给模型():
    """仓库 ID 在上下文里,不该让模型去猜 —— 从模型可见参数表里摘掉。"""
    skill = next(s for s in load_skills() if s.name == "ci_failure_triage")
    params = _exposed_parameters(skill)

    assert "repo_id" not in params["properties"]
    assert "repo_id" not in params["required"]
    # 业务参数要保留
    assert "number" in params["properties"]
    assert params["required"] == ["number"]


async def test_通过工具路径能跑通整个技能(db_with_snapshot, repo_id):
    install_skill_tools()
    ctx = ToolContext(db=db_with_snapshot, repo_id=repo_id)
    result = await execute("skill__repo_health_report", {}, ctx)

    assert result.data["skill"] == "repo_health_report"
    assert result.data["steps_executed"] == 2
    assert "repo_health" in result.summary


async def test_含写操作的技能会被标成写操作(tmp_path):
    """包一层封装不能成为绕过人工确认的后门。"""
    (tmp_path / "writes.yaml").write_text(
        "name: writes\n"
        "description: 里面调了写工具\n"
        "steps:\n"
        "  - tool: draft_action\n"
        "    args:\n"
        "      action: comment_on_issue\n"
        "      target: 'issue#1'\n",
        encoding="utf-8",
    )
    skill = load_skills(tmp_path)[0]
    assert _is_write_skill(skill) is True

    install_skill_tools(tmp_path)
    assert REGISTRY["skill__writes"].is_write is True


def test_只读技能不会被误标为写操作():
    skill = next(s for s in load_skills() if s.name == "repo_health_report")
    assert _is_write_skill(skill) is False


def test_坏技能文件被跳过而不是整个失败(tmp_path):
    (tmp_path / "broken.yaml").write_text("name: broken\n# 没有 steps\n", encoding="utf-8")
    (tmp_path / "good.yaml").write_text(
        "name: good\ndescription: ok\nsteps:\n  - tool: repo_health\n", encoding="utf-8")
    names = {s.name for s in load_skills(tmp_path)}
    assert names == {"good"}, "坏文件应当跳过,好文件照常加载"


async def test_技能运行时是异步的():
    """同步版只能用 asyncio.run,在已有事件循环里会直接抛错 —— 必须异步。"""
    import inspect

    assert inspect.iscoroutinefunction(SkillRuntime.run)