"""权限与风险策略。

集中一处,不散落在 Prompt 里 —— 高风险路径判定如果写进 Prompt,
就变成「模型说了算」,而不是系统说了算。
"""

from __future__ import annotations

import fnmatch

# PR 改动命中这些路径即视为高风险。用 glob 便于覆盖目录与后缀两类写法。
HIGH_RISK_PATHS: frozenset[str] = frozenset(
    {
        "**/auth/**",
        "**/security/**",
        "**/crypto/**",
        "**/permissions*",
        "**/middleware/auth*",
        "**/migrations/**",
        ".github/workflows/**",
        "**/*.pem",
        "**/*.key",
        "**/Dockerfile",
        "**/docker-compose*.yml",
        "**/pyproject.toml",
        "**/package.json",
    }
)

# 写操作白名单。白名单之外一律拒绝,没有「先执行再检查」这条路。
WRITE_ACTIONS: frozenset[str] = frozenset(
    {"comment_on_issue", "add_labels", "close_issue", "reopen_issue"}
)

# 高风险动作在草稿上标 high,前端需要二次确认
HIGH_RISK_ACTIONS: frozenset[str] = frozenset({"close_issue", "reopen_issue"})

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": set(),
    "member": set(WRITE_ACTIONS),
    "maintainer": set(WRITE_ACTIONS),
}

ROLES: tuple[str, ...] = ("viewer", "member", "maintainer")


class PermissionDenied(Exception):
    """越权。调用方必须把它记进 audit_logs(403 也要留痕)。"""


def is_high_risk_path(path: str) -> bool:
    """路径是否为高风险。统一用 / 分隔后再匹配,避免 Windows 反斜杠漏判。"""
    normalized = path.replace("\\", "/")
    # 注意:不能用 lstrip("./") —— 那是按字符集剥离,会把 ".github" 的前导点一起吃掉,
    # 结果 .github/workflows 这类模式永远匹配不上。
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch("/" + normalized, pattern)
        for pattern in HIGH_RISK_PATHS
    )


def risk_level(action: str) -> str:
    return "high" if action in HIGH_RISK_ACTIONS else "low"


def assert_can_write(role: str, action: str) -> None:
    if action not in WRITE_ACTIONS:
        raise PermissionDenied(f"动作 {action!r} 不在写操作白名单内")
    if role not in ROLE_PERMISSIONS:
        raise PermissionDenied(f"未知角色 {role!r}")
    if action not in ROLE_PERMISSIONS[role]:
        raise PermissionDenied(f"角色 {role!r} 无权执行 {action!r}")