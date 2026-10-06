"""POST /api/chat/stream —— SSE 流式对话。

关键实现细节:Agent 与 SSE 生成器之间用 asyncio.Queue 解耦。
如果直接在生成器里 await Agent,那么 done 之前一个字节都发不出去,
验收要求的「逐事件可见进度」就不成立了。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.chat_agent import ChatAgent
from app.api.auth import get_role
from app.config import settings
from app.core.context import ContextAssembler
from app.core.memory_extract import deposit
from app.db import models as m
from app.db.session import SessionLocal, get_db
from app.observability.events import sse_format
from app.observability.tracing import RunTracer
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter()

HEARTBEAT_SECONDS = 15
# 客户端断开后,先给 Agent 这么长时间做协作式收尾(以便部分结果落库);
# 超时则由定时器硬取消,保证一定停得下来
CANCEL_GRACE_SECONDS = 5


def get_tracer(db: Session = Depends(get_db)) -> RunTracer:
    """生产:轨迹用独立会话写;测试通过 dependency_overrides 换成同一会话。"""
    return RunTracer(db, session_factory=SessionLocal)


def _resolve_session(db: Session, repo_id: int, session_key: str) -> m.Session:
    row = db.scalar(
        select(m.Session).where(m.Session.repo_id == repo_id, m.Session.title == session_key)
    )
    if row is None:
        row = m.Session(repo_id=repo_id, title=session_key)
        db.add(row)
        db.commit()
    return row


@router.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    role: str = Depends(get_role),
    db: Session = Depends(get_db),
    tracer: RunTracer = Depends(get_tracer),
) -> StreamingResponse:
    session_row = _resolve_session(db, req.repo_id, req.session_id)
    run = tracer.start_run(repo_id=req.repo_id, session_id=session_row.id,
                           question=req.message, mode=settings.llm_mode)

    async def gen() -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()
        # 客户端断开时置位。Agent 与工作流据此提前收手 ——
        # 否则用户关掉页面后,后端仍会把所有模型调用跑完,按量计费上是真金白银。
        cancel = asyncio.Event()

        async def emit(kind: str, data: dict) -> None:
            if cancel.is_set():
                return
            await queue.put((kind, data))

        async def worker() -> None:
            try:
                await emit("run_started", {
                    "run_id": run.id, "session_id": req.session_id,
                    "repo_id": req.repo_id, "mode": settings.llm_mode,
                })

                history, info = ContextAssembler().assemble(
                    db, session_id=session_row.id, repo_id=req.repo_id, question=req.message
                )
                await emit("context", {
                    "repo": info.repo, "history_turns": info.history_turns,
                    "memory_hits": info.memory_hits,
                    "budget": {"total": info.budget_total, "used": info.budget_used},
                    "compressed": info.compressed,
                })

                outcome = await ChatAgent().run(
                    db, repo_id=req.repo_id, question=req.message, history=history,
                    emit=emit, role=role, run_id=run.id, session_id=session_row.id,
                    cancel=cancel,
                )

                for record in outcome.tool_calls:
                    tracer.record_tool_call(
                        agent_run_id=run.id, task_run_id=None, tool=record.tool,
                        args=record.args, summary=record.summary, error=record.error,
                    )
                    _persist_workflow(tracer, run.id, record)

                for citation in outcome.citations:
                    await emit("citation", citation)

                # 会话消息落库,供下一轮组装上下文
                db.add(m.Message(session_id=session_row.id, role="human",
                                 content=req.message, run_id=run.id))
                db.add(m.Message(session_id=session_row.id, role="assistant",
                                 content=outcome.answer, run_id=run.id))
                db.commit()

                # 沉淀:把本次运行里值得跨会话复用的经验写进候选池。
                # 只入候选、不生效 —— 要人工批准后才参与召回。
                # 失败不许影响本次回答,所以单独兜住异常。
                # 被中断的运行不沉淀:它的结论本来就是「没跑完」,进候选池只会污染。
                if outcome.stop_reason == "cancelled":
                    logger.info("运行被中断,跳过记忆沉淀 run_id=%s", run.id)
                else:
                    try:
                        deposited = deposit(db, outcome, repo_id=req.repo_id,
                                            session_id=session_row.id, run_id=run.id)
                        if deposited:
                            logger.info("本次运行沉淀了 %s 条记忆候选 run_id=%s",
                                        len(deposited), run.id)
                    except Exception:  # noqa: BLE001
                        logger.exception("记忆沉淀失败(不影响本次回答) run_id=%s", run.id)

                status = "succeeded" if outcome.stop_reason == "completed" else "failed"
                if outcome.stop_reason == "cancelled":
                    status = "cancelled"
                tracer.finish_run(run.id, status=status, stop_reason=outcome.stop_reason,
                                  answer=outcome.answer, steps=outcome.steps,
                                  total_tokens=outcome.total_tokens)

                await emit("done", {
                    "run_id": run.id,
                    "answer": outcome.answer,
                    "citations": outcome.citations,
                    "next_steps": outcome.next_steps,
                    "stop_reason": outcome.stop_reason,
                    "steps": outcome.steps,
                    "drafts": outcome.drafts,
                    "total_tokens": outcome.total_tokens,
                })
            except asyncio.CancelledError:
                # 客户端断开导致任务被取消:如实记成 cancelled,
                # 绝不能让一条被中断的运行在轨迹里留成 running 或 succeeded
                logger.info("对话流被取消(客户端断开) run_id=%s", run.id)
                try:
                    tracer.finish_run(run.id, status="cancelled", stop_reason="cancelled",
                                      answer="", steps=0)
                except Exception:  # noqa: BLE001
                    logger.warning("取消时写运行轨迹失败 run_id=%s", run.id, exc_info=True)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("对话流处理失败 run_id=%s", run.id)
                tracer.finish_run(run.id, status="failed", stop_reason="upstream_error",
                                  answer="", steps=0)
                await emit("error", {"message": f"处理失败:{exc}"})
            finally:
                with contextlib.suppress(Exception):
                    await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    # 长任务期间保活,避免反向代理掐连接
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                kind, payload = item
                yield sse_format(kind, payload)
        finally:
            # 生成器被关闭 = 客户端断开了(或正常结束时 worker 已完成)。
            #
            # 这里踩过两个坑,都不是小事:
            #
            # 1. 只 `await task` 不取消 → 服务端陪着把整个工作流跑完,
            #    用户早就关掉页面了,模型调用还在继续计费。
            # 2. 先 `await asyncio.wait_for(asyncio.shield(task), ...)` 等协作式收尾 →
            #    生成器 teardown **本身就处于取消状态**,这个 await 会立刻抛
            #    CancelledError,于是谁都没被取消,后台任务一路跑完并写成 succeeded。
            #
            # 所以:同步置位 + 用定时器兜底硬取消,teardown 里一个 await 都不要有。
            # 协作式取消有 CANCEL_GRACE_SECONDS 的窗口(Agent 在步骤边界和 token
            # 之间检查 cancel),超时则由定时器取消,保证一定停得下来。
            if not task.done():
                cancel.set()
                loop = asyncio.get_running_loop()
                timer = loop.call_later(CANCEL_GRACE_SECONDS, task.cancel)
                task.add_done_callback(lambda _: timer.cancel())

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


def _persist_workflow(tracer: RunTracer, run_id: int, record) -> None:  # noqa: ANN001
    """把工作流工具的结果落成 WorkflowRun / TaskRun 轨迹。"""
    if record.tool != "run_workflow" or record.error:
        return
    data = _tool_data(record)
    tasks = data.get("tasks") or []
    if not tasks:
        return
    workflow = tracer.start_workflow(run_id, question="workflow")
    for item in tasks:
        task_run = tracer.start_task(
            workflow.id, task_key=item.get("task_key", ""), agent=item.get("agent", ""),
            title=item.get("title", ""), depends_on=item.get("depends_on") or [],
        )
        tracer.finish_task(task_run.id, status=item.get("status", "succeeded"),
                           output=item.get("output") or {}, error=item.get("error"))
    tracer.finish_workflow(workflow.id, status="succeeded",
                           replan_count=int(data.get("replan_count") or 0))


def _tool_data(record) -> dict:  # noqa: ANN001
    return getattr(record, "data", None) or {}