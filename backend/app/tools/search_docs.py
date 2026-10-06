"""研发资料检索(RAG 通道)。

代码与实时状态都不走这里 —— 这里只查历史文档、设计说明、讨论记录。
"""

from __future__ import annotations

from app.rag.retriever import hybrid_search
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def search_docs(ctx: ToolContext, query: str = "", top_k: int = 6, **_: object) -> ToolResult:
    evidence = hybrid_search(ctx.db, ctx.repo_id, str(query), top_k=int(top_k))

    if not evidence:
        # 检索不到就明说,不允许模型自由发挥
        return ToolResult(
            tool="search_docs",
            summary=f"知识库中未找到与「{query}」相关的资料。",
            data={"query": query, "evidence": []},
            empty=True,
        )

    # 只有够格的命中才挂成引用;弱命中仍然返回给模型看(它需要上下文判断),
    # 但不作为「依据」呈现给用户 —— 少给引用比给错引用代价小。
    citable = [ev for ev in evidence if ev.strong]
    citations = [
        {"doc_path": ev.doc_path, "heading_path": ev.heading_path,
         "score": round(ev.score, 6), "preview": ev.content[:160]}
        for ev in citable
    ]
    summary = (
        f"在知识库中找到 {len(evidence)} 段相关资料,最相关的是"
        f"「{evidence[0].citation}」。"
    )
    if not citable:
        summary += "(这些命中与问题的相关度不足,仅供参考,不作为依据。)"
    return ToolResult(
        tool="search_docs",
        summary=summary,
        data={"query": query, "evidence": citations},
        evidence_refs=[ev.citation for ev in evidence],
        citations=citations,
    )


register(ToolSpec(
    name="search_docs",
    description="在项目知识库(历史文档、设计说明)中做混合检索,返回带引用的证据。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索问题"},
            "top_k": {"type": "integer", "description": "返回证据条数,默认 6"},
        },
        "required": ["query"],
    },
    handler=search_docs,
))