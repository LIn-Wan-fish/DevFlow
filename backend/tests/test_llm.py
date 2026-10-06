"""Task 5 验收。

核心断言只有一个意思:**Mock 必须真的产出 tool_calls**。
否则 ChatAgent 的循环与执行约束一次都不会被执行到,单测就是摆设。
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.core.llm import DeterministicChatModel, get_chat_model, get_structured_model
from app.core.prompts.roles import role_marker
from app.schemas.issue import IssueTriage


def _tools(*names: str) -> list[dict]:
    return [{"name": n, "description": f"{n} 工具", "parameters": {"type": "object"}} for n in names]


def test_mock_模型返回真实_tool_calls():
    model = get_chat_model(role="chat_agent", tools=_tools("debug_ci"))
    msg = model.invoke([SystemMessage(role_marker("chat_agent")), HumanMessage("CI #512 为什么失败?")])
    assert isinstance(msg, AIMessage)
    assert msg.tool_calls, "Mock 必须真的产出 tool_calls,否则 Agent 循环没被测试到"
    assert msg.tool_calls[0]["name"] == "debug_ci"
    assert msg.tool_calls[0]["args"] == {"number": 512}


def test_mock_模型依据问题选择不同工具():
    model = get_chat_model(role="chat_agent", tools=_tools("review_pr", "debug_ci"))
    picks = {}
    for question in ("PR #12 能不能合?", "CI #512 为什么失败?"):
        msg = model.invoke([SystemMessage(role_marker("chat_agent")), HumanMessage(question)])
        picks[question] = msg.tool_calls[0]["name"]
    assert picks["PR #12 能不能合?"] == "review_pr"
    assert picks["CI #512 为什么失败?"] == "debug_ci"


def test_mock_模型拿到工具结果后收尾不再调工具():
    model = get_chat_model(role="chat_agent", tools=_tools("debug_ci"))
    messages = [
        SystemMessage(role_marker("chat_agent")),
        HumanMessage("CI #512 为什么失败?"),
        AIMessage("", tool_calls=[{"name": "debug_ci", "args": {"number": 512}, "id": "c1"}]),
        ToolMessage('{"root_cause": "断言失败 expected 200 got 401"}', tool_call_id="c1"),
    ]
    msg = model.invoke(messages)
    assert not msg.tool_calls
    assert msg.content
    assert "401" in msg.content


def test_需要综合判断时路由到工作流工具():
    model = get_chat_model(role="chat_agent", tools=_tools("run_workflow"))
    msg = model.invoke([
        SystemMessage(role_marker("chat_agent")),
        HumanMessage("检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布"),
    ])
    assert msg.tool_calls[0]["name"] == "run_workflow"


def test_单点_pr_问题不进工作流():
    """「PR #12 能不能合?」是单点问题,不该被丢进多 Agent 工作流。"""
    model = get_chat_model(role="chat_agent", tools=_tools("run_workflow", "review_pr"))
    msg = model.invoke([SystemMessage(role_marker("chat_agent")), HumanMessage("PR #12 能不能合?")])
    assert msg.tool_calls[0]["name"] == "review_pr"


def test_没有可用工具时直接给结论而不是空转():
    model = get_chat_model(role="chat_agent", tools=[])
    msg = model.invoke([SystemMessage(role_marker("chat_agent")), HumanMessage("你好")])
    assert not msg.tool_calls and msg.content


def test_bind_tools_接受_langchain_工具对象():
    from langchain_core.tools import StructuredTool

    tool = StructuredTool.from_function(lambda number: "ok", name="debug_ci", description="x")
    bound = DeterministicChatModel(role="chat_agent").bind_tools([tool])
    assert bound.tools == ["debug_ci"]


# --------------------------------------------------------------------- 结构化输出


def test_结构化输出确定性():
    model = get_structured_model(IssueTriage, role="issue_agent")
    out = model.invoke([
        SystemMessage(role_marker("issue_agent")),
        HumanMessage('{"number": 24, "title": "登录报错", "labels": ["bug", "priority:P0", "area:auth"], "body": "线上 401"}'),
    ])
    assert isinstance(out, IssueTriage)
    assert out.priority == "P0"
    assert out.category == "Bug"
    assert out.recommended_assignee == "wangwu"
    assert out.action_items


def test_结构化输出可复现():
    model = get_structured_model(IssueTriage, role="issue_agent")
    messages = [SystemMessage(role_marker("issue_agent")), HumanMessage('{"title": "x", "body": "y"}')]
    assert model.invoke(messages) == model.invoke(messages)


def test_结构化输出对_feature_分类正确():
    model = get_structured_model(IssueTriage, role="issue_agent")
    out = model.invoke([
        SystemMessage(role_marker("issue_agent")),
        HumanMessage('{"number": 3, "title": "Feature: 增加桌面化能力", "labels": ["feature", "priority:P2", "area:ui"], "body": "### What problem does this solve?\\n希望桌面化"}'),
    ])
    assert out.category == "Feature"
    assert out.priority == "P2"
    assert out.recommended_assignee == "lisi"


def test_chat_agent_不支持结构化输出():
    with pytest.raises(NotImplementedError):
        DeterministicChatModel(role="chat_agent").with_structured_output(IssueTriage)


def test_openai_模式返回_ChatOpenAI(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.deepseek.com/v1")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_model", "deepseek-chat")

    model = get_chat_model(role="chat_agent")
    assert model.model_name == "deepseek-chat"
    assert "deepseek" in str(model.openai_api_base)

def test_json_指令必须描述嵌套字段():
    """真实模型靠这段说明才知道每个 task 要哪些字段;漏了就是 12 个 missing 校验错误。"""
    from app.core.llm import _json_instructions
    from app.schemas.workflow import Plan

    text = _json_instructions(Plan)
    assert "tasks" in text
    for nested in ("task_key", "agent", "title", "depends_on"):
        assert nested in text, f"嵌套字段 {nested} 没有被描述"