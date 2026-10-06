"""多 Agent 工作流(LangGraph)。

调度规则(每条都有测试):
- 依赖未满足的任务不启动
- 无依赖的任务真并行(asyncio.gather,并发上限可配)
- 依赖任务失败 → 下游显式 skipped,不静默当成功
- 重规划有次数上限(MAX_REPLAN),不允许无限空转
- Observer 的冲突由硬规则算出后传给 Synthesis,不允许被和稀泥
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.ci_debug_agent import CIDebugAgent
from app.agents.issue_agent import IssueAgent
from app.agents.observer import ObserverAgent, hard_rules
from app.agents.planner import PlannerAgent
from app.agents.pr_review_agent import PRReviewAgent
from app.agents.safety_agent import SafetyAgent
from app.agents.synthesis import SynthesisAgent
from app.config import settings
from app.core.workflow_rules import collect_facts
from app.db import models as m
from app.github.conclusions import healthy_filter
from app.observability.events import emit_event
from app.schemas.workflow import Observation, WorkflowAgent

logger = logging.getLogger(__name__)

SYNTHESIS_KEY = "synthesis"

# 任务执行者的展示名,同时也是 SSE 里 tool_call 的工具名
AGENT_TOOL_NAME = {
    WorkflowAgent.ISSUE.value: "analyze_issue",
    WorkflowAgent.PR_REVIEW.value: "review_pr",
    WorkflowAgent.CI_DEBUG.value: "debug_ci",
    WorkflowAgent.SAFETY.value: "safety_check",
}

_EXPLICIT_RE = re.compile(r"\b(pr|ci|issue)\s*#?\s*(\d+)", re.IGNORECASE)
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class WorkflowOutcome:
    answer: str
    tasks: list[dict] = field(default_factory=list)
    observation: dict = field(default_factory=dict)
    replan_count: int = 0
    status: str = "succeeded"
    facts: dict = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    synthesis: dict = field(default_factory=dict)


class WorkflowState(TypedDict, total=False):
    question: str
    tasks: list[dict]
    replan_count: int
    replan_needed: bool
    facts: dict
    conflicts: list[str]
    gaps: list[str]
    final: dict


def resolve_targets(db: Session, repo_id: int, question: str) -> dict[str, int | None]:
    """确定各 Agent 要分析的目标编号。

    问题里写了编号就用编号;没写就取仓库里最该看的那个
    (优先级最高的 open Issue / 最新的 open PR / 最近一次失败 CI)。
    """
    targets: dict[str, int | None] = {"issue_agent": None, "pr_review_agent": None, "ci_debug_agent": None}

    for kind, number in _EXPLICIT_RE.findall(question):
        key = {"pr": "pr_review_agent", "ci": "ci_debug_agent", "issue": "issue_agent"}[kind.lower()]
        targets[key] = int(number)

    if targets["issue_agent"] is None:
        open_issues = db.scalars(
            select(m.Issue).where(m.Issue.repo_id == repo_id, m.Issue.state == "open")
        ).all()
        if open_issues:
            def rank(issue: m.Issue) -> tuple[int, int]:
                best = 9
                for label in issue.labels or []:
                    found = re.search(r"priority:(p[0-3])", str(label).lower())
                    if found:
                        best = min(best, _PRIORITY_ORDER.get(found.group(1).upper(), 9))
                return (best, issue.number)

            targets["issue_agent"] = min(open_issues, key=rank).number

    if targets["pr_review_agent"] is None:
        pr = db.scalar(
            select(m.PullRequest).where(
                m.PullRequest.repo_id == repo_id, m.PullRequest.state == "open"
            ).order_by(m.PullRequest.number.desc())
        )
        targets["pr_review_agent"] = pr.number if pr else None

    if targets["ci_debug_agent"] is None:
        failing = db.scalar(
            select(m.CiRun).where(
                m.CiRun.repo_id == repo_id, healthy_filter(m.CiRun.conclusion)
            ).order_by(m.CiRun.number.desc())
        )
        targets["ci_debug_agent"] = failing.number if failing else None

    return targets


async def _execute_task(db: Session, repo_id: int, task: dict) -> tuple[dict, str | None]:
    """执行一个专用 Agent 任务,返回 (输出, 降级说明)。"""
    agent = task["agent"]
    number = task.get("number")
    degraded: str | None = None

    if agent == WorkflowAgent.ISSUE.value:
        out = await IssueAgent().run(db, repo_id=repo_id, number=number)
    elif agent == WorkflowAgent.PR_REVIEW.value:
        out = await PRReviewAgent().run(db, repo_id=repo_id, number=number)
    elif agent == WorkflowAgent.CI_DEBUG.value:
        out = await CIDebugAgent().run(db, repo_id=repo_id, number=number)
    elif agent == WorkflowAgent.SAFETY.value:
        # 给了具体动作就评那个动作;否则做仓库级安全扫描。
        # 原先这里没有分支,真实模型规划出 safety 任务时会抛 ValueError 把整个维度判死。
        action = (task.get("action") or "").strip()
        if action:
            out = await SafetyAgent().run(
                db, action=action, target=(task.get("target") or "").strip()
            )
        else:
            out = SafetyAgent().check_repo(db, repo_id)
    else:
        raise ValueError(f"未知的执行者: {agent}")

    payload = out.model_dump(mode="json")

    if agent == WorkflowAgent.CI_DEBUG.value:
        # 把 CI 的真实结论文并进输出:Observer 判断冲突需要它,
        # 而 CIDebug 本身只描述根因,不含流水线状态。
        run = db.scalar(
            select(m.CiRun).where(m.CiRun.repo_id == repo_id, m.CiRun.number == number)
        )
        if run is None:
            degraded = f"CI #{number} 的运行记录不存在,无法核对流水线状态。"
            payload["conclusion"] = "unknown"
        else:
            payload["conclusion"] = run.conclusion

    return payload, degraded


async def run_workflow(
    db: Session,
    *,
    repo_id: int,
    question: str,
    emit,
    tracer: Any | None = None,
    cancel: asyncio.Event | None = None,
) -> WorkflowOutcome:
    """跑一次多 Agent 工作流。

    `cancel` 用于客户端断开时收手:每执行一个任务之前检查一次。
    没有它的话,用户点了「停止」或者直接关掉页面,后端仍会把
    所有专用 Agent 和 Synthesis 全部跑完 —— 按量计费的模型上这是真金白银。
    """
    if emit is None:
        async def emit(kind: str, data: dict) -> None:  # noqa: ANN001
            return None

    def cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    targets = resolve_targets(db, repo_id, question)
    degraded: list[str] = []

    async def planner_node(state: WorkflowState) -> dict:
        # 用「是否已有任务」判断是不是重入,而不是用 replan_count:
        # 首次进入时 count 同样是 0,拿它判断会让重规划分支永远进不去,
        # 图就会在 planner→dispatch→observer 之间无限打转(实测触发 RecursionError)。
        replanning = bool(state.get("tasks"))
        if not replanning:
            if cancelled():
                # 一进来就被取消:连规划那次模型调用都不要发起
                await emit_event(emit, "plan", {"tasks": [], "replan_count": 0,
                                                "cancelled": True})
                return {"tasks": [], "replan_count": 0}
            plan = await PlannerAgent().run(db, question=question, targets=targets)
            tasks: list[dict] = []
            for spec in plan.tasks:
                item = spec.model_dump(mode="json")
                item.update({"status": "pending", "output": {}, "error": None})
                tasks.append(item)
            await emit_event(emit, "plan", {
                "tasks": [
                    {"task_key": t["task_key"], "agent": t["agent"], "title": t["title"],
                     "depends_on": t["depends_on"], "number": t.get("number")}
                    for t in tasks
                ],
                "replan_count": 0,
            })
            return {"tasks": tasks, "replan_count": 0}

        # 重规划:只把失败/跳过的任务重置,已经成功的保留,不重复烧一遍
        tasks = [dict(t) for t in state["tasks"]]
        reset: list[str] = []
        for task in tasks:
            if task["status"] in ("failed", "skipped"):
                task["status"] = "pending"
                task["error"] = None
                task["output"] = {}
                reset.append(task["task_key"])
        await emit_event(emit, "plan", {
            "replan": True,
            "replan_count": state.get("replan_count", 0),
            "reset_tasks": reset,
            "tasks": [
                {"task_key": t["task_key"], "agent": t["agent"], "title": t["title"],
                 "depends_on": t["depends_on"], "number": t.get("number")}
                for t in tasks
            ],
        })
        return {"tasks": tasks, "replan_count": state.get("replan_count", 0) + 1}

    async def dispatch_node(state: WorkflowState) -> dict:
        tasks = [dict(t) for t in state["tasks"]]
        by_key = {t["task_key"]: t for t in tasks}
        analyzable = [t for t in tasks if t["agent"] != WorkflowAgent.SYNTHESIS.value]
        semaphore = asyncio.Semaphore(settings.workflow_parallelism)

        async def guarded(task: dict) -> None:
            async with semaphore:
                tool = AGENT_TOOL_NAME.get(task["agent"], task["agent"])
                if cancelled():
                    # 已经断开就不要启动新的 Agent —— 结果没人接收,调用却照样计费
                    task["status"] = "skipped"
                    task["error"] = "客户端已断开,任务取消"
                    await emit_event(emit, "task_finished", {
                        "task_key": task["task_key"], "agent": task["agent"],
                        "status": "skipped", "error": task["error"],
                    })
                    return
                task["status"] = "running"
                task["started"] = True
                await emit_event(emit, "tool_call", {
                    "task_key": task["task_key"], "tool": tool,
                    "args": {"number": task.get("number")},
                })
                try:
                    output, note = await _execute_task(db, repo_id, task)
                    task["status"] = "succeeded"
                    task["output"] = output
                    if note:
                        degraded.append(note)
                    summary = _summarize(output)
                    await emit_event(emit, "tool_result", {
                        "task_key": task["task_key"], "tool": tool, "summary": summary,
                        "evidence_refs": _refs(task),
                    })
                except Exception as exc:  # noqa: BLE001
                    task["status"] = "failed"
                    task["error"] = f"{type(exc).__name__}: {exc}"
                    await emit_event(emit, "tool_result", {
                        "task_key": task["task_key"], "tool": tool, "error": str(exc),
                    })
                finally:
                    await emit_event(emit, "task_finished", {
                        "task_key": task["task_key"], "agent": task["agent"],
                        "status": task["status"], "error": task.get("error"),
                    })

        while True:
            # 依赖失败 → 显式跳过,不静默当成功
            for task in analyzable:
                if task["status"] != "pending":
                    continue
                if any(by_key[k]["status"] in ("failed", "skipped") for k in task["depends_on"]):
                    task["status"] = "skipped"
                    task["error"] = "依赖任务未成功"
                    await emit_event(emit, "task_finished", {
                        "task_key": task["task_key"], "agent": task["agent"], "status": "skipped",
                        "error": task["error"],
                    })

            ready = [
                t for t in analyzable
                if t["status"] == "pending"
                and all(by_key[k]["status"] == "succeeded" for k in t["depends_on"])
            ]
            if not ready:
                break
            if cancelled():
                # 剩余任务保持 pending,由下面统一标成 skipped
                break
            for task in ready:
                await emit_event(emit, "task_started", {
                    "task_key": task["task_key"], "agent": task["agent"], "title": task["title"],
                })
            await asyncio.gather(*[guarded(t) for t in ready])

        # 取消后仍处于 pending 的任务要显式标记,不能留着假装还没跑
        for task in analyzable:
            if task["status"] == "pending":
                task["status"] = "skipped"
                task["error"] = "客户端已断开,任务取消"
                await emit_event(emit, "task_finished", {
                    "task_key": task["task_key"], "agent": task["agent"],
                    "status": "skipped", "error": task["error"],
                })

        return {"tasks": tasks}

    async def observer_node(state: WorkflowState) -> dict:
        tasks = state["tasks"]
        results = [
            {"task_key": t["task_key"], "agent": t["agent"], "number": t.get("number"),
             "output": t["output"], "status": t["status"]}
            for t in tasks
            if t["agent"] != WorkflowAgent.SYNTHESIS.value and t["status"] == "succeeded"
        ]
        failed_errors = [
            t["error"] for t in tasks
            if t["agent"] != WorkflowAgent.SYNTHESIS.value
            and t["status"] == "failed" and t.get("error")
        ]

        rules = hard_rules(results, tasks, [*degraded, *failed_errors])
        if cancelled():
            # 断开后不再调用模型:硬规则已经能算出冲突与缺口,再烧一次没有意义
            agent_observation = Observation()
        else:
            agent_observation = await ObserverAgent().run(
                db, question=question, results=results, tasks=tasks,
                degraded=[*degraded, *failed_errors],
            )

        # 硬规则的冲突一定保留;模型只做补充
        conflicts = list(dict.fromkeys([*rules.conflicts, *agent_observation.conflicts]))
        gaps = list(dict.fromkeys([*rules.gaps, *agent_observation.gaps]))

        await emit_event(emit, "observation", {
            "gaps": gaps, "conflicts": conflicts, "safety": rules.safety,
        })

        # 只有执行层面的缺口才值得重规划:像「评审建议补测试」这种,
        # 重跑一次也不会自己消失,只会白白空转。
        exec_gap = any(
            t["status"] in ("failed", "skipped")
            for t in tasks if t["agent"] != WorkflowAgent.SYNTHESIS.value
        ) or bool(degraded)
        return {
            "facts": collect_facts(results),
            "conflicts": conflicts,
            "gaps": gaps,
            "replan_needed": exec_gap,
        }

    async def synthesis_node(state: WorkflowState) -> dict:
        tasks = [dict(t) for t in state["tasks"]]
        results = [
            {"task_key": t["task_key"], "agent": t["agent"], "number": t.get("number"),
             "output": t["output"], "status": t["status"]}
            for t in tasks
            if t["agent"] != WorkflowAgent.SYNTHESIS.value and t["status"] == "succeeded"
        ]
        if cancelled():
            # 客户端已断开:不生成结论,如实说明这次没跑完
            final = {
                "conclusion": "客户端已断开,本次分析未完成。已执行的任务结果保留在运行轨迹里。",
                "evidence": [f"{t['agent']} 已完成" for t in tasks
                             if t["status"] == "succeeded"],
                "next_steps": ["重新发起一次完整提问"],
                "confidence": "low",
            }
        else:
            try:
                synthesis = await SynthesisAgent().run(
                    db, question=question, results=results,
                    conflicts=state.get("conflicts") or [], gaps=state.get("gaps") or [],
                )
                final = synthesis.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                # 结构化输出两次修复重试都没救回来时,**不能让整个工作流陪葬**:
                # 各维度 Agent 已经跑完的结果仍然有价值(而且已经花了钱)。
                # 如实说明汇总失败并把原始结论交出去,而不是伪造一个结论。
                logger.warning("Synthesis 结构化输出失败,降级交付", exc_info=True)
                final = {
                    "conclusion": (
                        f"各维度分析已完成,但结论汇总失败({type(exc).__name__})。"
                        "下面是各 Agent 的原始结论,请人工判读。"
                    ),
                    "evidence": [
                        f"{t['agent']}: {_summarize(t.get('output') or {})}"
                        for t in tasks
                        if t["status"] == "succeeded"
                        and t["agent"] != WorkflowAgent.SYNTHESIS.value
                    ],
                    "next_steps": ["重试一次汇总,或人工综合上面各维度结论"],
                    "confidence": "low",
                }

        for task in tasks:
            if task["agent"] == WorkflowAgent.SYNTHESIS.value:
                task["status"] = "succeeded"
                task["output"] = final
                await emit_event(emit, "task_started", {
                    "task_key": task["task_key"], "agent": task["agent"], "title": task["title"],
                })
                await emit_event(emit, "task_finished", {
                    "task_key": task["task_key"], "agent": task["agent"], "status": "succeeded",
                })

        await emit_event(emit, "token", {"delta": final["conclusion"]})
        return {"tasks": tasks, "final": final}

    def should_replan(state: WorkflowState) -> str:
        if state.get("replan_needed") and state.get("replan_count", 0) < settings.max_replan:
            return "replan"
        return "synthesize"

    graph = StateGraph(WorkflowState)
    graph.add_node("planner", planner_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("observer", observer_node)
    graph.add_node("synthesis", synthesis_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "dispatch")
    graph.add_edge("dispatch", "observer")
    graph.add_conditional_edges("observer", should_replan,
                                {"replan": "planner", "synthesize": "synthesis"})
    graph.add_edge("synthesis", END)
    compiled = graph.compile()

    final_state = await compiled.ainvoke({"question": question, "replan_count": 0})
    tasks = final_state.get("tasks") or []
    final = final_state.get("final") or {}

    next_steps = final.get("next_steps") or []
    answer = final.get("conclusion") or "未能形成结论。"
    if next_steps:
        answer = answer + "\n\n下一步建议:\n" + "\n".join(f"- {s}" for s in next_steps)

    return WorkflowOutcome(
        answer=answer,
        tasks=tasks,
        observation={
            "gaps": final_state.get("gaps") or [],
            "conflicts": final_state.get("conflicts") or [],
        },
        replan_count=final_state.get("replan_count", 0),
        # 取消不再谎报 succeeded:轨迹要能区分「跑完了」和「被中断」
        status="cancelled" if cancelled() else "succeeded",
        facts=final_state.get("facts") or {},
        conflicts=final_state.get("conflicts") or [],
        gaps=final_state.get("gaps") or [],
        synthesis=final,
    )


def _summarize(output: dict) -> str:
    for key in ("rationale", "root_cause", "conclusion"):
        value = output.get(key)
        if value:
            return str(value)[:200]
    return "; ".join(f"{k}={v}" for k, v in list(output.items())[:3])[:200]


def _refs(task: dict) -> list[str]:
    number = task.get("number")
    agent = task.get("agent")
    prefix = {
        WorkflowAgent.ISSUE.value: "issue",
        WorkflowAgent.PR_REVIEW.value: "pr",
        WorkflowAgent.CI_DEBUG.value: "ci",
    }.get(agent, "task")
    return [f"{prefix}#{number}"] if number is not None else []