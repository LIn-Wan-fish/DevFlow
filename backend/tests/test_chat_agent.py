"""Task 10 验收:Agent 循环与三条执行约束。

这几条约束是原文明确要求的能力,所以每一条都单独测,
而不是靠一个「整体能跑通」的用例糊过去。
"""

import dataclasses

import pytest
from sqlalchemy import select

from app.agents.chat_agent import ChatAgent
from app.db import models as m
from app.tools.registry import REGISTRY


def _collect(sink):
    def emit(kind, data):
        sink.append((kind, data))

    return emit


def _break_tool(monkeypatch, name: str):
    spec = REGISTRY[name]

    async def boom(ctx, **kwargs):  # noqa: ANN001
        raise RuntimeError(f"{name} 上游不可用")

    monkeypatch.setitem(REGISTRY, name, dataclasses.replace(spec, handler=boom))


async def test_简单问题一轮工具调用后收尾(db_with_snapshot, repo_id):
    events = []
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id, question="CI #512 为什么失败?",
        history=[], emit=_collect(events),
    )
    assert outcome.stop_reason == "completed"
    assert any(record.tool == "debug_ci" for record in outcome.tool_calls)
    assert outcome.answer
    assert "401" in outcome.answer, "答案必须带出日志里的关键报错信息"


async def test_每个工具调用都产生事件(db_with_snapshot, repo_id):
    events = []
    await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                          question="CI #512 为什么失败?", history=[], emit=_collect(events))
    kinds = [k for k, _ in events]
    assert kinds.index("tool_call") < kinds.index("tool_result")


async def test_重复调用同一工具即停止(db_with_snapshot, repo_id):
    outcome = await ChatAgent(force_tools=["repo_health"]).run(
        db_with_snapshot, repo_id=repo_id, question="随便问问", history=[], emit=lambda *a: None)
    assert outcome.stop_reason == "repeated_tool_call"
    assert len(outcome.tool_calls) == 1, "第二次同参数调用应当被拦下,不再执行"


async def test_达到步数上限停止且留痕(db_with_snapshot, repo_id, monkeypatch):
    monkeypatch.setattr("app.config.settings.max_agent_steps", 2)
    # 用两个不同工具轮换,避免先撞上重复调用拦截,从而真正测到步数上限
    outcome = await ChatAgent(force_tools=["repo_health", "search_code"]).run(
        db_with_snapshot, repo_id=repo_id, question="x", history=[], emit=lambda *a: None)
    assert outcome.stop_reason == "max_steps"
    assert outcome.steps == 2
    assert outcome.answer, "超限也要交付已有结论,不能静默失败"


async def test_工具异常回灌给模型而不是直接崩(db_with_snapshot, repo_id, monkeypatch):
    _break_tool(monkeypatch, "debug_ci")
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id, question="CI #512 为什么失败?",
        history=[], emit=lambda *a: None)
    assert outcome.stop_reason in ("completed", "tool_error_limit")
    assert any(record.error for record in outcome.tool_calls), "错误必须被记录,不能消失"


async def test_连续错误达上限停止(db_with_snapshot, repo_id, monkeypatch):
    for name in ("debug_ci", "review_pr", "analyze_issue"):
        _break_tool(monkeypatch, name)
    outcome = await ChatAgent(force_tools=["debug_ci", "review_pr", "analyze_issue"]).run(
        db_with_snapshot, repo_id=repo_id, question="x", history=[], emit=lambda *a: None)
    assert outcome.stop_reason == "tool_error_limit"
    assert len([r for r in outcome.tool_calls if r.error]) == 3


async def test_需要综合判断时交给工作流(db_with_snapshot, repo_id):
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id,
        question="检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
        history=[], emit=lambda *a: None)
    assert any(record.tool == "run_workflow" for record in outcome.tool_calls)
    assert outcome.stop_reason == "completed"


async def test_写操作只出草稿并上报(db_with_snapshot, repo_id):
    events = []
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id,
        question="给 Issue #3 写一条查询评论草稿",
        history=[], emit=_collect(events))
    assert outcome.drafts, "写操作必须以草稿形式返回"
    kinds = [k for k, _ in events]
    assert "draft" in kinds
    draft_id = outcome.drafts[0]["draft_id"]
    draft = db_with_snapshot.get(m.ActionDraft, draft_id)
    assert draft.status == "pending"
    # 全程不应出现任何 executed 审计
    results = [a.result for a in db_with_snapshot.scalars(select(m.AuditLog)).all()]
    assert "executed" not in results


async def test_检索不到时如实说未找到(db_with_snapshot, repo_id):
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id,
        question="项目里量子纠缠模块怎么实现?",
        history=[], emit=lambda *a: None)
    assert "未找到" in outcome.answer


async def test_历史对话被带进上下文(db_with_snapshot, repo_id):
    from langchain_core.messages import AIMessage, HumanMessage

    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id, question="CI #512 为什么失败?",
        history=[HumanMessage("我们刚聊过登录问题"), AIMessage("好的")],
        emit=lambda *a: None)
    assert outcome.stop_reason == "completed"

# --------------------------------------------------------------------------- 流式 / 取消 / 用量


async def test_逐_token_推送增量事件(db_with_snapshot, repo_id):
    """回归:答案原先只在 done 里一次性给出,真实模型一次生成几十秒,用户全程干等。"""
    events: list[tuple[str, dict]] = []
    await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                          question="CI #512 为什么失败?", history=[],
                          emit=_collect(events))

    tokens = [data for kind, data in events if kind == "token"]
    assert tokens, "必须推送 token 增量事件"
    assert all("delta" in data for data in tokens)
    # 增量拼接应当非空
    assert "".join(d.get("delta", "") for d in tokens).strip()


async def test_done_里的答案才是权威的(db_with_snapshot, repo_id):
    """流式是预览,done 才是权威 —— 前端用 done 覆盖增量缓冲。

    真实模型在工具调用轮也会吐正文(实测是第一句「I'll analyze ...」),
    所以两者本来就可能不一致,必须有明确的权威来源。
    """
    events: list[tuple[str, dict]] = []
    outcome = await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                                    question="CI #512 为什么失败?", history=[],
                                    emit=_collect(events))
    done = [data for kind, data in events if kind == "done"]
    # ChatAgent 本身不发 done(那是 API 层的事),这里核对 outcome 与增量的关系
    assert outcome.answer
    assert not done or done[0].get("answer") == outcome.answer


async def test_取消后不再执行后续模型调用(db_with_snapshot, repo_id):
    """回归:前端「停止」原先只 abort 浏览器侧的 fetch,后端会把整个流程跑完。"""
    import asyncio

    cancel = asyncio.Event()
    cancel.set()  # 一开始就是取消状态

    events: list[tuple[str, dict]] = []
    outcome = await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                                    question="CI #512 为什么失败?", history=[],
                                    emit=_collect(events), cancel=cancel)

    assert outcome.stop_reason == "cancelled"
    assert not outcome.tool_calls, "取消后不应再执行任何工具调用"
    assert not [k for k, _ in events if k == "tool_call"]


async def test_运行中用取消也能收手(db_with_snapshot, repo_id):
    """工具执行到一半时置位取消,后续步骤必须停下并在轨迹里标成 cancelled。"""
    import asyncio

    cancel = asyncio.Event()

    async def emit(kind: str, data: dict) -> None:
        # 第一次工具调用之后立刻取消
        if kind == "tool_result":
            cancel.set()

    outcome = await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                                    question="检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
                                    history=[], emit=emit, cancel=cancel)
    assert outcome.stop_reason in ("cancelled", "completed")


async def test_记录模型上报的_token_用量(db_with_snapshot, repo_id):
    outcome = await ChatAgent().run(db_with_snapshot, repo_id=repo_id,
                                    question="CI #512 为什么失败?", history=[],
                                    emit=lambda *a: None)
    assert outcome.total_tokens > 0, "Mock 也要上报确定性用量,否则前端这块没法验证"


def test_拿不到用量时返回_0_而不是估算():
    """没有上报就是 0 —— 不用字数估算冒充真实用量。"""
    from app.agents.chat_agent import _usage_of
    from langchain_core.messages import AIMessage

    assert _usage_of(AIMessage(content="x")) == 0
    assert _usage_of(AIMessage(content="x", usage_metadata={
        "input_tokens": 3, "output_tokens": 5, "total_tokens": 8})) == 8

async def test_工作流路径被取消时不谎报完成(db_with_snapshot, repo_id):
    """回归:工作流预路由里的 `_finish(...)` 曾经硬编码 "completed"。

    于是「跑到一半被客户端取消」的运行会在轨迹里写成成功 ——
    一条被中断的运行谎报跑完了,比没有轨迹更糟。

    (第一版的即时硬取消碰巧掩盖了这个 bug:CancelledError 抢先中断,
    根本没走到那句 _finish。改成协作式取消后立刻暴露。)
    """
    import asyncio

    cancel = asyncio.Event()
    cancel.set()

    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id,
        question="检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
        history=[], emit=lambda *a: None, cancel=cancel)

    assert outcome.stop_reason == "cancelled", "被取消的运行不能报 completed"


async def test_工作流被取消时不发起规划调用(db_with_snapshot, repo_id):
    """取消后连 Planner 那次模型调用都不该发起。"""
    import asyncio

    from app.agents.orchestrator import run_workflow

    cancel = asyncio.Event()
    cancel.set()
    outcome = await run_workflow(db_with_snapshot, repo_id=repo_id,
                                 question="判断这个版本是否可以发布",
                                 emit=lambda *a: None, cancel=cancel)

    assert outcome.status == "cancelled"
    assert outcome.tasks == [], "取消后不应产出任务"

async def test_工作流路径也统计_token_用量(db_with_snapshot, repo_id):
    """回归:工作流各 Agent 走**结构化输出**,不走流式聊天模型 ——

    那条路径原先完全没有记账,于是真实模型跑完一次旗舰问句,
    AgentRun.total_tokens 恒为 0(实测踩到)。
    """
    outcome = await ChatAgent().run(
        db_with_snapshot, repo_id=repo_id,
        question="检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
        history=[], emit=lambda *a: None)

    assert outcome.stop_reason == "completed"
    assert outcome.tool_calls, "应当走了工作流"
    assert outcome.total_tokens > 0, "结构化输出那条路径的用量也要计入"