"""Agent 角色标记。

每个 Agent 的 system prompt 第一行必须带上 role_marker(...)。
确定性 Mock 模型靠它识别「现在是谁在说话」——
没有这个标记,Mock 就无法区分 IssueAgent 和 CIDebugAgent,只能瞎猜。
"""

from __future__ import annotations

import re
from enum import StrEnum


class AgentRole(StrEnum):
    CHAT = "chat_agent"
    PLANNER = "planner"
    OBSERVER = "observer"
    SYNTHESIS = "synthesis"
    ISSUE = "issue_agent"
    PR_REVIEW = "pr_review_agent"
    CI_DEBUG = "ci_debug_agent"
    SAFETY = "safety_agent"


MARKER = "[[AGENT_ROLE:{role}]]"
_ROLE_RE = re.compile(r"\[\[AGENT_ROLE:([a-z_]+)\]\]")


def role_marker(role: str) -> str:
    return MARKER.format(role=role)


def parse_role(text: str | None) -> str | None:
    if not text:
        return None
    match = _ROLE_RE.search(text)
    return match.group(1) if match else None