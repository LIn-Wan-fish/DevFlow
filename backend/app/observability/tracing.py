"""运行轨迹落库:AgentRun → WorkflowRun → TaskRun → ToolCall,四级可串。

生产用独立会话写轨迹(流式响应期间事务边界会和 SSE 事件交错);
单测把 session_factory 传 None,复用测试会话,免得为了可测性把生产逻辑改掉。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AgentRun, RunStatus, TaskRun, ToolCall, WorkflowRun


def _now() -> datetime:
    return datetime.now(UTC)


class RunTracer:
    def __init__(self, db: Session, session_factory: Callable[[], Session] | None = None) -> None:
        self.db = db
        self._factory = session_factory

    # ------------------------------------------------------------------ 内部

    def _write(self, fn: Callable[[Session], Any]) -> Any:
        if self._factory is None:
            result = fn(self.db)
            self.db.commit()
            return result
        session = self._factory()
        try:
            result = fn(session)
            session.commit()
            return result
        finally:
            session.close()

    # ------------------------------------------------------------------ AgentRun

    def start_run(self, *, repo_id: int, session_id: int | None, question: str,
                  mode: str) -> AgentRun:
        def op(db: Session) -> AgentRun:
            run = AgentRun(repo_id=repo_id, session_id=session_id, question=question,
                           status=RunStatus.RUNNING.value, mode=mode, started_at=_now())
            db.add(run)
            db.flush()
            return run

        run = self._write(op)
        return run

    def finish_run(self, run_id: int, *, status: str, stop_reason: str, answer: str,
                   steps: int, total_tokens: int = 0) -> None:
        def op(db: Session) -> None:
            run = db.get(AgentRun, run_id)
            if run is None:
                return
            run.status = status
            run.stop_reason = stop_reason
            run.answer = answer
            run.steps = steps
            # 只记模型**真实回报**的用量;拿不到就保持 0,不用估算值冒充
            run.total_tokens = total_tokens
            run.finished_at = _now()

        self._write(op)

    # ------------------------------------------------------------------ Workflow

    def start_workflow(self, agent_run_id: int, question: str) -> WorkflowRun:
        def op(db: Session) -> WorkflowRun:
            wf = WorkflowRun(agent_run_id=agent_run_id, question=question,
                             status=RunStatus.RUNNING.value, replan_count=0, started_at=_now())
            db.add(wf)
            db.flush()
            return wf

        return self._write(op)

    def finish_workflow(self, workflow_run_id: int, *, status: str, replan_count: int) -> None:
        def op(db: Session) -> None:
            wf = db.get(WorkflowRun, workflow_run_id)
            if wf is None:
                return
            wf.status = status
            wf.replan_count = replan_count
            wf.finished_at = _now()

        self._write(op)

    # ------------------------------------------------------------------ Task

    def start_task(self, workflow_run_id: int, *, task_key: str, agent: str, title: str,
                   depends_on: list[str]) -> TaskRun:
        def op(db: Session) -> TaskRun:
            task = TaskRun(workflow_run_id=workflow_run_id, task_key=task_key, agent=agent,
                           title=title, depends_on=list(depends_on), status="running",
                           started_at=_now())
            db.add(task)
            db.flush()
            return task

        return self._write(op)

    def finish_task(self, task_run_id: int, *, status: str, output: dict | None = None,
                    error: str | None = None) -> None:
        def op(db: Session) -> None:
            task = db.get(TaskRun, task_run_id)
            if task is None:
                return
            task.status = status
            task.output = output or {}
            task.error = error
            task.finished_at = _now()

        self._write(op)

    # ------------------------------------------------------------------ ToolCall

    def record_tool_call(self, *, agent_run_id: int | None, task_run_id: int | None,
                         tool: str, args: dict, summary: str = "", error: str | None = None,
                         latency_ms: int = 0) -> None:
        def op(db: Session) -> None:
            db.add(ToolCall(agent_run_id=agent_run_id, task_run_id=task_run_id, tool=tool,
                            args=args or {}, result_summary=summary, error=error,
                            latency_ms=latency_ms))

        self._write(op)


def load_trace(db: Session, run_id: int) -> dict:
    """一次取全一条运行轨迹,供前端「运行轨迹」抽屉使用。"""
    run = db.get(AgentRun, run_id)
    if run is None:
        return {}
    workflows = list(db.query(WorkflowRun).filter_by(agent_run_id=run_id).all())
    tasks = []
    for wf in workflows:
        tasks.extend(db.query(TaskRun).filter_by(workflow_run_id=wf.id).all())
    calls = list(db.query(ToolCall).filter_by(agent_run_id=run_id).all())
    return {
        "agent_run": {
            "id": run.id, "question": run.question, "status": run.status, "mode": run.mode,
            "stop_reason": run.stop_reason, "answer": run.answer, "steps": run.steps,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        },
        "workflow_runs": [
            {"id": wf.id, "status": wf.status, "replan_count": wf.replan_count}
            for wf in workflows
        ],
        "task_runs": [
            {"id": t.id, "task_key": t.task_key, "agent": t.agent, "title": t.title,
             "depends_on": t.depends_on, "status": t.status, "output": t.output,
             "error": t.error}
            for t in tasks
        ],
        "tool_calls": [
            {"id": c.id, "task_run_id": c.task_run_id, "tool": c.tool, "args": c.args,
             "result_summary": c.result_summary, "error": c.error, "latency_ms": c.latency_ms}
            for c in calls
        ],
    }