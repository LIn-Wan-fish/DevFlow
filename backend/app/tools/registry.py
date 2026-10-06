"""工具注册表。

两条硬约束由测试守住,不靠自觉:
1. is_write=True 的工具**有且仅有** draft_action —— 模型因此拿不到直接执行写操作的通道
2. 不存在任何以 execute 开头的工具名(防止有人后加一个 execute_action 把闸门绕过去)
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session


class UnknownToolError(Exception):
    pass


@dataclass
class ToolContext:
    db: Session
    repo_id: int
    role: str = "member"
    run_id: int | None = None
    session_id: int | None = None
    emit: Callable[[str, dict], Any] | None = None
    # 客户端断开时置位;长链路工具(如多 Agent 工作流)应据此提前收手
    cancel: Any = None


@dataclass
class ToolResult:
    tool: str
    summary: str
    data: dict = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    empty: bool = False

    def as_json(self) -> str:
        return json.dumps(
            {
                "tool": self.tool,
                "summary": self.summary,
                "data": self.data,
                "evidence_refs": self.evidence_refs,
                "citations": self.citations,
                "empty": self.empty,
            },
            ensure_ascii=False,
            default=str,
        )


Handler = Callable[..., Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Handler
    is_write: bool = False


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


def names() -> list[str]:
    return list(REGISTRY)


async def execute(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        # 明确报错,不做静默降级 —— 静默失败会让模型以为拿到了证据
        raise UnknownToolError(name)
    return await spec.handler(ctx, **(args or {}))


def as_langchain_tools() -> list[dict]:
    """OpenAI function-calling 格式,同时兼容 ChatOpenAI 与确定性 Mock。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in REGISTRY.values()
    ]