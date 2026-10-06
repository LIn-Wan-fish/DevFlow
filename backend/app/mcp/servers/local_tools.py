"""示例 MCP 服务端工具。

范围刻意收窄:只证明「外部能力能以统一协议接进来,并且入参会被校验」,
不实现完整 MCP 规范。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class ToolInputError(Exception):
    pass


def _require(args: dict, key: str, type_: type) -> Any:
    if key not in args:
        raise ToolInputError(f"缺少必填参数 {key}")
    value = args[key]
    if not isinstance(value, type_):
        raise ToolInputError(f"参数 {key} 类型应为 {type_.__name__}")
    return value


def echo(args: dict) -> dict:
    text = _require(args, "text", str)
    return {"echo": text}


def now(args: dict) -> dict:
    return {"now": datetime.now(UTC).isoformat()}


def word_count(args: dict) -> dict:
    text = _require(args, "text", str)
    return {"chars": len(text), "words": len(text.split())}


TOOLS: dict[str, tuple[str, Any, dict]] = {
    "echo": ("回显输入文本,用于验证调用链路", echo,
             {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    "now": ("返回服务器当前 UTC 时间", now, {"type": "object", "properties": {}, "required": []}),
    "word_count": ("统计文本字符数与词数", word_count,
                   {"type": "object", "properties": {"text": {"type": "string"}},
                    "required": ["text"]}),
}