"""RAGAS 指标 —— 通过独立容器计算。

**为什么不 in-process**:ragas 与本项目的 langchain 1.x 栈无法共存,实测:
  - ragas 0.2+/0.3+/0.4+ → 导入时引用 `langchain_community.chat_models.vertexai`(已移除)
  - ragas 0.1.22 → 能导入,但把 langchain 从 1.4.3 强降到 0.2.17,主程序随即崩在
    `Reviver.__init__() got an unexpected keyword argument 'allowed_objects'`
所以评测依赖被隔离在 services/ragas_eval 容器里,主程序通过 HTTP 调它。

**拿不到结果时一律如实说明原因**(mock 模式 / 服务未配置 / 服务连不上 / 没有检索上下文),
绝不编造指标数字 —— 这条和文章 7.5 节要求的「固定评测集 + 硬规则 + RAGAS」是一致的:
数字要么是真的,要么明确说没有。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm import get_chat_model
from app.rag.retriever import hybrid_search

logger = logging.getLogger(__name__)

RAG_DATASET = Path("tests/data/rag_eval_cases.json")
TIMEOUT_SECONDS = 600.0


def _load_cases() -> list[dict]:
    try:
        return json.loads(RAG_DATASET.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


async def _answer_with_context(question: str, contexts: list[str]) -> str:
    """只依据检索到的证据生成答案。

    刻意不复用 ChatAgent:这里要衡量的是**检索质量**,
    让它去调工具、做多轮会引入与检索无关的变量。
    """
    if not contexts:
        return "未检索到相关证据,无法回答。"
    evidence = "\n\n".join(f"[{i + 1}] {text}" for i, text in enumerate(contexts))
    model = get_chat_model(role="rag_eval")
    response = await model.ainvoke([HumanMessage(
        "只依据下面给出的证据回答问题,不要补充证据之外的内容;"
        "证据不足以回答时,直接说「未检索到相关证据」。\n\n"
        f"证据:\n{evidence}\n\n问题:{question}"
    )])
    return response.content if isinstance(response.content, str) else str(response.content)


async def run(db: Session, repo_id: int, mode: str) -> dict:
    """跑一轮 RAGAS 评测,返回可直接塞进 metrics 的字典。"""
    if mode == "mock":
        # 判分必须由真实模型完成 —— mock 模式下跑出来的数字没有意义
        return {"ragas": "skipped (mock 模式:判分需要真实模型)"}

    url = (settings.ragas_eval_url or "").rstrip("/")
    if not url:
        return {"ragas": "unavailable (未配置 RAGAS_EVAL_URL)"}

    cases = _load_cases()
    if not cases:
        return {"ragas": "unavailable (没有 RAG 评测集)"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            health = await client.get(f"{url}/health")
            health.raise_for_status()

            payload_cases = []
            for case in cases:
                hits = hybrid_search(db, repo_id, case["question"], top_k=4)
                contexts = [h.content for h in hits]
                payload_cases.append({
                    "question": case["question"],
                    "answer": await _answer_with_context(case["question"], contexts),
                    "contexts": contexts,
                    "ground_truth": case.get("ground_truth"),
                })

            response = await client.post(f"{url}/evaluate", json={"cases": payload_cases})
            response.raise_for_status()
            result = response.json()
    except Exception as exc:  # noqa: BLE001
        # 服务连不上就是连不上,如实说,不要让整个 eval 挂掉
        logger.warning("RAGAS 评测器不可用:%s", exc)
        return {"ragas": f"unavailable ({type(exc).__name__}: {str(exc)[:120]})"}

    if result.get("status") != "ok":
        return {"ragas": f"{result.get('status')} ({str(result.get('reason'))[:160]})"}

    return {
        "ragas": "ok",
        "ragas_version": result.get("ragas_version"),
        "ragas_samples": result.get("samples"),
        "ragas_scores": result.get("scores") or {},
        # 没算的指标要写明原因:例如 answer_relevancy 需要真实嵌入端点
        "ragas_skipped": result.get("skipped") or [],
    }