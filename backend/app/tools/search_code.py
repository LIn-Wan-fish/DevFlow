"""当前代码检索(Workspace 工具)。

代码**永不进向量库** —— 代码天天变,向量库里的副本必然过期。
当前代码只走这里:直接读工作区文件。
"""

from __future__ import annotations

from pathlib import Path

from app.db.seed import SNAPSHOT_DIR
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register

CODE_ROOT = SNAPSHOT_DIR / "code"
MAX_HITS = 20
TEXT_SUFFIXES = {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".java", ".rs", ".rb", ".sql", ".yml", ".yaml"}


def _iter_files() -> list[Path]:
    if not CODE_ROOT.exists():
        return []
    return [
        p for p in sorted(CODE_ROOT.rglob("*"))
        if p.is_file() and p.suffix in TEXT_SUFFIXES
    ]


async def search_code(ctx: ToolContext, query: str = "", **_: object) -> ToolResult:
    terms = [t for t in str(query).split() if t] or [str(query)]
    hits: list[dict] = []

    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(CODE_ROOT)).replace("\\", "/")
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(term.lower() in lowered for term in terms if term):
                hits.append({"path": rel, "line_no": line_no, "snippet": line.strip()[:200]})
                if len(hits) >= MAX_HITS:
                    break
        if len(hits) >= MAX_HITS:
            break

    if not hits:
        return ToolResult(
            tool="search_code",
            summary=f"未找到与「{query}」相关的代码。",
            data={"query": query, "hits": []},
            empty=True,
        )
    files = sorted({h["path"] for h in hits})
    summary = f"在 {len(files)} 个文件里找到 {len(hits)} 处与「{query}」相关的代码:{'、'.join(files[:3])}。"
    return ToolResult(
        tool="search_code",
        summary=summary,
        data={"query": query, "hits": hits},
        evidence_refs=files,
    )


register(ToolSpec(
    name="search_code",
    description="在当前仓库的工作区代码里搜索(读的是最新代码,不是历史文档)。",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "搜索词,可以是标识符或关键字"}},
        "required": ["query"],
    },
    handler=search_code,
))