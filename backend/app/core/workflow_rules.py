"""工作流的硬规则。

冲突与缺口必须由规则算出来,不能指望 Prompt 自觉 ——
「PR 说可合、CI 说阻塞」这种矛盾如果交给模型判断,
它大概率会和稀泥给一个「建议进一步确认」。

放在 core 而不是 agents 下,是为了让 llm.py(确定性 Mock)和 observer.py
共用同一套规则,避免两边判断标准漂移。
"""

from __future__ import annotations

import re
from typing import Any

from app.github.conclusions import is_failed_conclusion


def collect_facts(results: list[dict[str, Any]]) -> dict[str, Any]:
    """把各任务的输出摊平成便于比对的信号。"""
    pr: list[dict] = []
    ci: list[dict] = []
    issues: list[dict] = []
    for item in results:
        agent = item.get("agent")
        output = item.get("output") or {}
        if agent == "pr_review_agent":
            pr.append({"number": item.get("number"), "decision": output.get("decision"),
                       "risk_level": output.get("risk_level"),
                       "missing_checks": output.get("missing_checks") or []})
        elif agent == "ci_debug_agent":
            ci.append({"number": item.get("number"), "conclusion": output.get("conclusion"),
                       "root_cause": output.get("root_cause"),
                       "confidence": output.get("confidence")})
        elif agent == "issue_agent":
            issues.append({"number": item.get("number"), "priority": output.get("priority"),
                           "category": output.get("category")})
    return {"pr": pr, "ci": ci, "issues": issues}


def detect_conflicts(facts: dict[str, Any]) -> list[str]:
    """结论冲突。这是多 Agent 存在的意义所在,必须显式报出来。"""
    conflicts: list[str] = []
    failing = [c for c in facts.get("ci", []) if is_failed_conclusion(c.get("conclusion"))]
    for pr in facts.get("pr", []):
        if pr.get("decision") == "merge" and failing:
            numbers = "、".join(f"CI #{c['number']}" for c in failing)
            conflicts.append(
                f"PR #{pr.get('number')} 的审查结论是「可合入」,但 {numbers} 结论为「失败」——"
                f"改动审查与流水线状态不一致,不能只按其中一方决策。"
            )
        if pr.get("decision") == "hold" and not failing and facts.get("ci"):
            conflicts.append(
                f"PR #{pr.get('number')} 的审查结论是「暂缓」,但所有 CI 均通过 ——"
                f"阻塞点来自评审而非流水线,需要人工确认。"
            )
    return conflicts


def detect_gaps(
    facts: dict[str, Any], tasks: list[dict[str, Any]], degraded: list[str] | None = None
) -> list[str]:
    """证据缺口。"""
    gaps: list[str] = []
    for item in tasks:
        status = item.get("status")
        if status == "failed":
            gaps.append(f"任务「{item.get('title')}」执行失败,结论缺少这部分证据。")
        elif status == "skipped":
            gaps.append(f"任务「{item.get('title')}」因依赖失败被跳过,结论缺少这部分证据。")

    for ci in facts.get("ci", []):
        if ci.get("confidence") == "low":
            gaps.append(f"CI #{ci.get('number')} 缺少可用的失败日志,根因无法确认。")

    for pr in facts.get("pr", []):
        if pr.get("risk_level") == "high" and pr.get("missing_checks"):
            gaps.append(
                f"PR #{pr.get('number')} 命中高风险路径,仍有未完成的检查:"
                + "、".join(str(x) for x in pr["missing_checks"])
            )

    for reason in degraded or []:
        gaps.append(reason)
    return gaps
# --------------------------------------------------------------------------- 路由判据

# 「简单问题走工具、复杂问题进多 Agent 工作流」是**架构决定**,不该由模型自由裁量:
# 真实模型很可能直接连调几个工具,导致多 Agent 能力永远不触发。所以判据放在代码里,
# 两个模式共用同一套规则。
_SIGNAL_PATTERNS = {
    "issue": re.compile(r"\bissues?\b", re.IGNORECASE),
    "pr": re.compile(r"\bprs?\b|pull request", re.IGNORECASE),
    "ci": re.compile(r"\bci\b|构建|流水线", re.IGNORECASE),
}
_RELEASE_RE = re.compile(r"版本|发布|上线|release|能不能上", re.IGNORECASE)


def needs_workflow(question: str) -> bool:
    """是否需要多 Agent 协作。

    两条判据,刻意收紧,避免把「PR #12 能不能合?」这种单点问题也丢进工作流:
    - 问题横跨两类以上数据源(Issue / PR / CI)
    - 或者明确在问版本发布
    """
    lowered = (question or "").lower()
    matched = sum(1 for pattern in _SIGNAL_PATTERNS.values() if pattern.search(lowered))
    return matched >= 2 or bool(_RELEASE_RE.search(lowered))

# --------------------------------------------------------------------------- 工具路由

# 顺序有讲究:先判断「是不是复杂问题」,再挑单个工具。
SINGLE_TOOL_RULES: list[tuple[tuple[str, ...], str]] = [
    (("周报", "weekly"), "weekly_report"),
    (("评论", "关闭 issue", "打标签", "草稿", "关掉"), "draft_action"),
    (("文档", "规范", "怎么用", "知识库", "说明"), "search_docs"),
    (("代码", "实现", "哪个文件", "在哪"), "search_code"),
    (("ci", "构建失败", "流水线", "构建挂"), "debug_ci"),
    (("pr", "pull request", "审查", "review", "合并"), "review_pr"),
    (("issue", "分诊", "优先级", "复杂度", "分给谁"), "analyze_issue"),
]

_NUMBER_RE = re.compile(r"#\s*(\d+)")
_KEYWORD_NUMBER_RE = re.compile(r"\b(?:ci|pr|issue)\s*#?\s*(\d+)", re.IGNORECASE)


def first_number(text: str) -> int | None:
    match = _NUMBER_RE.search(text) or _KEYWORD_NUMBER_RE.search(text)
    return int(match.group(1)) if match else None


def pick_tool(question: str, available: set[str], *, allow_fallback: bool = True) -> str | None:
    """按信号挑一个工具。

    allow_fallback=False 时不做 repo_health 兜底 —— 用于「模型空手作答时强制取证」,
    那种场景下逼着它去查仓库概览反而答非所问。
    """
    if needs_workflow(question) and "run_workflow" in available:
        return "run_workflow"
    lowered = (question or "").lower()
    for keywords, tool in SINGLE_TOOL_RULES:
        if tool in available and any(keyword in lowered for keyword in keywords):
            return tool
    if allow_fallback and "repo_health" in available:
        return "repo_health"
    return None


def tool_args(tool: str, question: str) -> dict:
    number = first_number(question)
    if tool in ("debug_ci", "review_pr", "analyze_issue"):
        return {"number": number} if number is not None else {}
    if tool in ("search_docs", "search_code"):
        return {"query": question}
    if tool == "run_workflow":
        return {"question": question}
    if tool == "draft_action":
        target = f"issue#{number}" if number is not None else "issue#3"
        return {
            "action": "comment_on_issue",
            "target": target,
            "body": "这条评论由 DevFlow AI 生成草稿,等待人工确认后再提交。",
        }
    return {}

# 「让我写条评论草稿」这类明确的写意图。刻意收窄:
# 必须同时出现「写/生成/给我/来一条」和「草稿/评论」,
# 否则「文档里的评论规范是什么」会被误判成写操作。
# 关键:写动词必须出现在名词**之前**(「写一条评论草稿」),
# 或者名词是「草稿」这种本身就表示待执行产物的词。
# 否则「PR #12 的评论谁写的」这种被动/疑问句会被误判成写操作 —— 这条是实测踩出来的。
_DRAFT_INTENT_RE = re.compile(
    r"(?:写|生成|拟|来一条|给我|帮我)[^。;!?]{0,12}(?:草稿|评论)"
    r"|草稿[^。;!?]{0,12}(?:写|生成|拟|来一条)"
)


def wants_draft(question: str) -> bool:
    """是否明确要求生成写操作草稿。

    写操作必须走草稿 + 人工确认 —— 这是系统级安全要求。
    实测真实模型有时会跳过 draft_action、只给一段文字建议,
    那样安全闸门就完全没被触发,所以这里做确定性预路由。
    """
    return bool(_DRAFT_INTENT_RE.search(question or ""))