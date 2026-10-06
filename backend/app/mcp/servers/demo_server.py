"""一个**真实的 MCP server**,走官方 SDK 的 stdio transport。

用途:证明「外部能力能以统一协议接进来」这件事是真的 ——
它由后端作为子进程拉起,通过 JSON-RPC over stdio 通信,
而不是同一个进程里直接函数调用。

对外暴露三个工具,都刻意选成**确定性**的(不依赖网络、不依赖时间窗口),
这样测试和演示都稳定:

- `now`             当前 UTC 时间
- `count_text`      统计字符/词/行数
- `compare_semver`  比较语义化版本号 —— 判断「这个版本能不能发布」时真的用得上

单独运行(便于调试):
    python -m app.mcp.servers.demo_server
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="devflow-demo",
    instructions="DevFlow AI 的外部工具服务端,提供时间、文本统计与版本比较。",
)

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](.*))?$")


def _parse_semver(version: str) -> tuple[int, int, int, str]:
    match = _SEMVER_RE.match((version or "").strip())
    if not match:
        raise ValueError(f"不是合法的语义化版本号:{version!r}(应形如 1.2.3)")
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre or ""


@server.tool()
def now() -> dict:
    """返回服务器当前的 UTC 时间(ISO 8601)。"""
    moment = datetime.now(UTC)
    return {"utc": moment.isoformat(), "epoch_seconds": int(moment.timestamp())}


@server.tool()
def count_text(text: str) -> dict:
    """统计一段文本的字符数、词数与行数。"""
    return {
        "chars": len(text),
        "words": len(text.split()),
        "lines": len(text.splitlines()) or (1 if text else 0),
    }


@server.tool()
def compare_semver(left: str, right: str) -> dict:
    """比较两个语义化版本号,返回 -1 / 0 / 1 与人类可读的结论。

    预发布版本(如 1.2.3-rc.1)小于同号的正式版 —— 这条规则在判断能否发布时会用到。
    """
    l_major, l_minor, l_patch, l_pre = _parse_semver(left)
    r_major, r_minor, r_patch, r_pre = _parse_semver(right)

    l_core, r_core = (l_major, l_minor, l_patch), (r_major, r_minor, r_patch)
    if l_core != r_core:
        result = -1 if l_core < r_core else 1
    elif l_pre == r_pre:
        result = 0
    elif not l_pre:          # 正式版 > 预发布版
        result = 1
    elif not r_pre:
        result = -1
    else:
        result = -1 if l_pre < r_pre else 1

    wording = {0: "两者等价", -1: f"{left} 早于 {right}", 1: f"{left} 晚于 {right}"}[result]
    return {"result": result, "conclusion": wording}


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()