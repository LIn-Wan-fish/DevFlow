"""SSE 事件定义与组帧。"""

from __future__ import annotations

import inspect
import json
from enum import StrEnum


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    CONTEXT = "context"
    PLAN = "plan"
    TASK_STARTED = "task_started"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TASK_FINISHED = "task_finished"
    OBSERVATION = "observation"
    TOKEN = "token"
    CITATION = "citation"
    DRAFT = "draft"
    DONE = "done"
    ERROR = "error"


def sse_format(event: str, data: dict, *, ensure_ascii: bool = False) -> str:
    """单个 SSE 帧。

    ensure_ascii=False 是有意的:中文要人可读,
    否则前端执行轨迹里全是 \\u767b\\u5f55 这种东西,排查问题时没法看。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=ensure_ascii)}\n\n"


async def emit_event(emit, kind: str, data: dict) -> None:
    """兼容同步与异步回调。

    单测里 emit 通常是同步 lambda,生产里是往 asyncio.Queue 投递的协程。
    两种都支持,免得为了测试把生产代码改成同步。
    """
    result = emit(kind, data)
    if inspect.isawaitable(result):
        await result