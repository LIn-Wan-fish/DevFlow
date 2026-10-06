"""Embedding 双模式。

mock 实现不是「随便返回个向量」:它必须是
  确定性(同文本同向量)、已归一化(便于余弦)、且共享词越多越相似。
第三点尤其重要 —— 如果所有文本的向量都差不多,检索测试就永远是绿的,
那这个测试等于没写。
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from app.config import settings

EMBED_DIM = settings.embed_dim

_ASCII_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _tokens(text: str) -> list[str]:
    """中英混合分词:英文按词,中文按「单字 + 相邻双字」。

    取双字是为了让「登录接口」和「登录接口变更」共享特征,
    单字是为了兜住只出现一次的字。
    """
    lowered = (text or "").lower()
    tokens = _ASCII_RE.findall(lowered)
    for run in _CJK_RE.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _hash_vector(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[index] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


@lru_cache(maxsize=1)
def _openai_client():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.embed_model or "text-embedding-3-small",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.embed_mode == "mock":
        return [_hash_vector(t, EMBED_DIM) for t in texts]
    return _openai_client().embed_documents(texts)


def embed_query(text: str) -> list[float]:
    if settings.embed_mode == "mock":
        return _hash_vector(text, EMBED_DIM)
    return _openai_client().embed_query(text)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))