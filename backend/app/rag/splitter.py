"""结构感知切分。

不按固定字数硬切 —— 那样会把「登录接口 > v1.2 变更」这类语义边界切碎,
检索回来的片段没有上下文,引用也就无从谈起。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CHUNK_TOKENS = 512
OVERLAP_PARAGRAPHS = 1

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_CODE_BOUNDARY_RE = re.compile(r"^(?:def |class |func |type |export function |export const )")


@dataclass
class Chunk:
    heading_path: str
    content: str
    chunk_index: int
    token_count: int
    symbols: list[str] = field(default_factory=list)


def rough_token_count(text: str) -> int:
    """粗略 token 估算:中文按字、英文按 4 字符 1 token。够用且无依赖。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(re.sub(r"[\u4e00-\u9fff]", "", text))
    return cjk + other // 4


def _split_long(heading_path: str, body: str, start_index: int) -> list[Chunk]:
    """超长小节按段落二次切分,并保留末尾 1 段重叠,避免切断上下文。"""
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    chunks: list[Chunk] = []
    buffer: list[str] = []
    index = start_index

    def flush() -> None:
        nonlocal buffer, index
        if not buffer:
            return
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(heading_path, text, index, rough_token_count(text)))
            index += 1
        buffer = buffer[-OVERLAP_PARAGRAPHS:] if OVERLAP_PARAGRAPHS else []

    for paragraph in paragraphs:
        candidate = "\n\n".join([*buffer, paragraph])
        if rough_token_count(candidate) > MAX_CHUNK_TOKENS and buffer:
            flush()
        buffer.append(paragraph)
    # flush 会保留重叠段,收尾时直接落盘,不再保留
    if buffer:
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(heading_path, text, index, rough_token_count(text)))
    return chunks


def split_document(path: str, text: str) -> list[Chunk]:
    """Markdown 按标题层级切;代码按 def/class 边界切。"""
    is_markdown = path.endswith((".md", ".markdown", ".mdx"))
    if is_markdown:
        return _split_markdown(text)
    return _split_code(path, text)


def _split_markdown(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    index = 0

    def heading_path() -> str:
        return " > ".join(title for _, title in stack)

    def flush() -> None:
        nonlocal buffer, index
        body = "\n".join(buffer).strip()
        buffer = []
        if not body:
            return
        if rough_token_count(body) > MAX_CHUNK_TOKENS:
            produced = _split_long(heading_path(), body, index)
            chunks.extend(produced)
            index += len(produced)
            return
        chunks.append(Chunk(heading_path(), body, index, rough_token_count(body)))
        index += 1

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
            buffer.append(line)
            continue
        buffer.append(line)
    flush()
    return chunks


def _split_code(path: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[str] = []
    symbol = path
    index = 0

    def flush() -> None:
        nonlocal current, index
        body = "\n".join(current).strip()
        current = []
        if not body:
            return
        if rough_token_count(body) > MAX_CHUNK_TOKENS:
            produced = _split_long(symbol, body, index)
            chunks.extend(produced)
            index += len(produced)
            return
        chunks.append(Chunk(symbol, body, index, rough_token_count(body), symbols=[symbol]))
        index += 1

    for line in text.splitlines():
        if _CODE_BOUNDARY_RE.match(line) and current:
            flush()
            symbol = line.strip().split("(")[0]
        current.append(line)
    flush()
    return chunks