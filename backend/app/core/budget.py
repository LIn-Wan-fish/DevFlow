"""上下文预算分配与逐级压缩。

压缩顺序是**设计的一部分**,不是实现细节:
先压工具结果(信息密度最低、而且可以随时重取),
再截检索证据(可按 rerank 分数重取),
最后才动对话历史 —— 历史丢了就再也拿不回来了。

system 段永不裁剪:它承载角色与行为约束,裁掉等于换了个人。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.splitter import rough_token_count

# 顺序本身是契约,有测试锁住
COMPRESSION_ORDER: tuple[str, ...] = ("tool_results", "evidence", "history")

TOOL_RESULT_SUMMARY_CHARS = 80
MIN_HISTORY_TURNS = 1


@dataclass
class EvidenceItem:
    text: str
    score: float = 0.0


@dataclass
class AssembledContext:
    system: str
    summary: str = ""
    history: list[dict] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class BudgetedContext:
    system: str
    summary: str
    history: list[dict]
    tool_results: list[str]
    evidence: list[EvidenceItem]
    compressed: list[str]
    total_tokens: int

    @property
    def used_segments(self) -> dict[str, int]:
        return {
            "system": rough_token_count(self.system),
            "summary": rough_token_count(self.summary),
            "history": sum(rough_token_count(h.get("content", "")) for h in self.history),
            "tool_results": sum(rough_token_count(t) for t in self.tool_results),
            "evidence": sum(rough_token_count(e.text) for e in self.evidence),
        }


def allocate(context: AssembledContext, total: int) -> BudgetedContext:
    tool_results = list(context.tool_results)
    evidence = list(context.evidence)
    history = [dict(h) for h in context.history]
    compressed: list[str] = []

    def cost() -> int:
        return (
            rough_token_count(context.system)
            + rough_token_count(context.summary)
            + sum(rough_token_count(h.get("content", "")) for h in history)
            + sum(rough_token_count(t) for t in tool_results)
            + sum(rough_token_count(e.text) for e in evidence)
        )

    if cost() <= total:
        return BudgetedContext(context.system, context.summary, history, tool_results,
                               evidence, [], cost())

    # ① 工具结果 → 摘要
    if tool_results:
        tool_results = [
            t if len(t) <= TOOL_RESULT_SUMMARY_CHARS else t[:TOOL_RESULT_SUMMARY_CHARS] + "…"
            for t in tool_results
        ]
        compressed.append("tool_results")

    # ② 证据 → 按 rerank 分数从低到高丢
    if cost() > total and evidence:
        evidence.sort(key=lambda item: (-item.score, item.text))
        while evidence and cost() > total:
            evidence.pop()  # 丢当前分数最低的
        compressed.append("evidence")

    # ③ 历史 → 从最旧开始丢,但保最近一轮(否则回答没有对象)
    if cost() > total and len(history) > MIN_HISTORY_TURNS:
        while len(history) > MIN_HISTORY_TURNS and cost() > total:
            history.pop(0)
        compressed.append("history")

    return BudgetedContext(context.system, context.summary, history, tool_results,
                           evidence, compressed, cost())