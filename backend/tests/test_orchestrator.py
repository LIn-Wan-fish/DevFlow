"""Task 11 验收:多 Agent 工作流的五条调度规则。"""

import asyncio
import time

import pytest

from app.agents.orchestrator import run_workflow
from app.schemas.workflow import Plan, TaskSpec

QUESTION = "检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布"


def _noop(kind, data):
    return None


def _collect(sink):
    def emit(kind, data):
        sink.append((kind, data))

    return emit


async def test_拆出的任务有依赖关系(db_with_snapshot, repo_id):
    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    keys = {t["task_key"] for t in out.tasks}
    assert len(keys) >= 3
    synthesis = [t for t in out.tasks if t["agent"] == "synthesis"][0]
    assert synthesis["depends_on"], "汇总任务必须依赖前置任务,否则它拿不到证据"


async def test_无依赖任务并行执行(db_with_snapshot, repo_id, monkeypatch):
    async def slow(db, repo_id, task):  # noqa: ANN001
        await asyncio.sleep(0.25)
        return {"summary": task["task_key"]}, None

    monkeypatch.setattr("app.agents.orchestrator._execute_task", slow)

    started = time.perf_counter()
    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    elapsed = time.perf_counter() - started

    parallel = [t for t in out.tasks if not t["depends_on"] and t["agent"] != "synthesis"]
    assert len(parallel) >= 2, "这个场景本来就该拆出多个互相独立的检查"
    # 串行需要 0.25 * n;并行应显著短于这个值
    assert elapsed < 0.25 * len(parallel), f"看起来是串行的: elapsed={elapsed:.2f}s n={len(parallel)}"


async def test_依赖任务失败时下游被跳过而不是当成功(db_with_snapshot, repo_id, monkeypatch):
    async def fake_plan(self, db, **kwargs):  # noqa: ANN001
        return Plan(
            tasks=[
                TaskSpec(task_key="t1", agent="pr_review_agent", title="先审 PR",
                         depends_on=[], number=12),
                TaskSpec(task_key="t2", agent="ci_debug_agent", title="再看 CI",
                         depends_on=["t1"], number=512),
                TaskSpec(task_key="synthesis", agent="synthesis", title="汇总",
                         depends_on=["t1", "t2"]),
            ]
        )

    async def boom(self, db, **kwargs):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.agents.planner.PlannerAgent.run", fake_plan)
    monkeypatch.setattr("app.agents.pr_review_agent.PRReviewAgent.run", boom)

    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    statuses = {t["task_key"]: t["status"] for t in out.tasks}
    assert statuses["t1"] == "failed"
    assert statuses["t2"] == "skipped", "依赖失败必须显式 skipped,不能静默当成功"
    assert any("t1" in g or "失败" in g for g in out.gaps)


async def test_observer_报出_pr_与_ci_的冲突(db_with_snapshot, repo_id):
    """PR 审查说可合、CI 说失败 —— 这是这个工作流存在的意义,必须报出来。"""
    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    assert out.conflicts, f"未报出冲突,observation={out.observation}"
    assert any("CI" in c for c in out.conflicts)
    # 结论里必须正面回应冲突,而不是和稀泥
    assert "冲突" in out.answer or "暂缓" in out.answer


async def test_观察结论进入最终结论(db_with_snapshot, repo_id):
    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    assert out.synthesis["conclusion"]
    assert out.synthesis["evidence"], "结论必须能列出证据来源"
    assert out.synthesis["next_steps"]


async def test_重规划有次数上限(db_with_snapshot, repo_id, monkeypatch):
    async def boom(self, db, **kwargs):  # noqa: ANN001
        raise RuntimeError("always fails")

    monkeypatch.setattr("app.agents.pr_review_agent.PRReviewAgent.run", boom)

    out = await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION, emit=_noop)
    from app.config import settings

    assert out.replan_count <= settings.max_replan, "不允许无限重规划空转"
    assert out.synthesis, "重规划耗尽后仍必须给出结论(哪怕结论是证据不足)"


async def test_事件顺序符合人读顺序(db_with_snapshot, repo_id):
    events = []
    await run_workflow(db_with_snapshot, repo_id=repo_id, question=QUESTION,
                       emit=_collect(events))
    kinds = [k for k, _ in events]
    assert kinds[0] == "plan"
    assert kinds.count("task_started") == kinds.count("task_finished")
    assert kinds.index("observation") > kinds.index("task_finished")
    assert kinds.index("tool_call") < kinds.index("tool_result")


async def test_目标编号能从问题里解析(db_with_snapshot, repo_id):
    out = await run_workflow(db_with_snapshot, repo_id=repo_id,
                             question="检查 PR #12 和 CI #512 的状态", emit=_noop)
    numbers = {t["agent"]: t.get("number") for t in out.tasks}
    assert numbers.get("pr_review_agent") == 12
    assert numbers.get("ci_debug_agent") == 512

def test_写草稿意图识别要收窄():
    """必须同时出现「写/生成」类和「草稿/评论」,避免把只读咨询误判成写操作。"""
    from app.core.workflow_rules import wants_draft

    assert wants_draft("给 Issue #3 写一条查询评论草稿")
    assert wants_draft("帮我生成一条评论")
    assert wants_draft("草稿写一下")
    # 以下都不该被判成写操作
    assert not wants_draft("文档里的评论规范是什么")
    assert not wants_draft("PR #12 的评论谁写的")
    assert not wants_draft("CI #512 为什么失败?")

# --------------------------------------------------------------------------- 调度穷尽性


async def test_所有声明过的执行者都能被调度(db_with_snapshot, repo_id):
    """回归:WorkflowAgent 里声明了 safety_agent,但调度器只认识 issue/pr/ci 三种。

    真实模型被问到「这个版本能不能发布」时会规划出一个 safety 任务,
    于是 `_execute_task` 抛 ValueError,整个安全维度被判死 ——
    而这条路径在快照数据的固定问法下从没被触发过。

    这个用例对枚举里的每个执行者都跑一遍,以后再加执行者却忘了补分支,这里就会红。
    """
    from sqlalchemy import select

    from app.agents.orchestrator import _execute_task
    from app.db import models as m
    from app.schemas.workflow import WorkflowAgent

    issue = db_with_snapshot.scalar(select(m.Issue).where(m.Issue.repo_id == repo_id))
    pr = db_with_snapshot.scalar(select(m.PullRequest).where(m.PullRequest.repo_id == repo_id))
    ci = db_with_snapshot.scalar(select(m.CiRun).where(m.CiRun.repo_id == repo_id))

    cases = [
        (WorkflowAgent.ISSUE, {"number": issue.number}),
        (WorkflowAgent.PR_REVIEW, {"number": pr.number}),
        (WorkflowAgent.CI_DEBUG, {"number": ci.number}),
        (WorkflowAgent.SAFETY, {}),
    ]
    for agent, extra in cases:
        task = {"agent": agent.value, "task_key": "k", "title": "t", **extra}
        payload, _ = await _execute_task(db_with_snapshot, repo_id, task)
        assert isinstance(payload, dict), f"{agent.value} 没有可用的调度分支"


async def test_safety_任务无具体动作时走仓库级扫描(db_with_snapshot, repo_id):
    from app.agents.orchestrator import _execute_task

    payload, degraded = await _execute_task(
        db_with_snapshot, repo_id,
        {"agent": "safety_agent", "task_key": "safety", "title": "发布前安全与合规风险检查"},
    )
    assert payload["level"] in ("low", "medium", "high")
    assert payload["draft_only"] is True
    assert payload["reasons"]
    assert degraded is None


async def test_safety_任务带具体动作时评那个动作(db_with_snapshot, repo_id):
    from app.agents.orchestrator import _execute_task

    payload, _ = await _execute_task(
        db_with_snapshot, repo_id,
        {"agent": "safety_agent", "task_key": "safety", "title": "评估评论草稿",
         "action": "comment_issue", "target": "issue#3"},
    )
    assert payload["level"] in ("low", "medium", "high")