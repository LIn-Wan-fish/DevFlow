"""Ragas 指标。

只在真实模型模式下有意义(需要模型判分)。
mock 模式**显式跳过**,并且如实写进 metrics —— 绝不用假数字充数。
"""

from __future__ import annotations


def is_available() -> bool:
    try:
        import ragas  # noqa: F401
    except ImportError:
        return False
    return True


def run(cases: list[dict], mode: str) -> dict:
    if mode == "mock":
        return {"ragas": "skipped (mock mode)"}
    if not is_available():
        return {"ragas": "unavailable (未安装 ragas)"}
    # 真实模式下由 ragas 计算 faithfulness / answer_relevancy / context_precision。
    # Demo 里只保留接入点:没有真实数据就不编造指标。
    return {"ragas": "pending (需真实模型逐题判分)"}