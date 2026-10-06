"""独立的 RAGAS 评测服务。

**为什么要单独一个容器**:ragas 与本项目主程序的 langchain 1.x 栈**无法共存**,实测:

- ragas 0.2 / 0.3 / 0.4 → 导入时引用 `langchain_community.chat_models.vertexai`(已被移除)
  → `ModuleNotFoundError`
- ragas 0.1.22 → 能导入,但会把 langchain 从 1.4.3 **强行降到 0.2.17**,
  主程序随即崩在 `Reviver.__init__() got an unexpected keyword argument 'allowed_objects'`

硬凑只有两种结果:要么主程序坏,要么没有 ragas。所以把评测依赖隔离到这个容器,
主程序只在需要时通过 HTTP 调它 —— 依赖冲突被限制在一个可丢弃的边界内。

**拿不到结果时一律如实返回原因**(未配置模型、没有真嵌入、ra gas 报错),
绝不编造指标数字。
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="DevFlow RAGAS Evaluator", version="0.1.0")


class Case(BaseModel):
    question: str
    answer: str
    contexts: list[str] = Field(default_factory=list)
    ground_truth: str | None = None


class EvaluateRequest(BaseModel):
    cases: list[Case]


def _ragas_version() -> str:
    try:
        import importlib.metadata as md

        return md.version("ragas")
    except Exception:  # noqa: BLE001
        return "unknown"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "ragas_version": _ragas_version(),
        "llm_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "embed_mode": os.environ.get("EMBED_MODE", "mock"),
    }


def _build_llm() -> Any:
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    return LangchainLLMWrapper(ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        temperature=0.0,
    ))


def _build_embeddings() -> Any | None:
    """只有配了真实嵌入端点时才返回;mock 模式返回 None。

    `answer_relevancy` 依赖嵌入。没有真嵌入就算不出来 —— 与其塞个假向量,
    不如把这个指标明确标成"未计算"。
    """
    if os.environ.get("EMBED_MODE", "mock") != "openai":
        return None
    if not os.environ.get("EMBED_MODEL"):
        return None
    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(OpenAIEmbeddings(
        model=os.environ.get("EMBED_MODEL", ""),
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    ))


@app.post("/evaluate")
def evaluate_cases(req: EvaluateRequest) -> dict[str, Any]:
    if not os.environ.get("OPENAI_API_KEY"):
        return {"status": "unavailable", "reason": "未配置 OPENAI_API_KEY,无法判分"}

    usable = [c for c in req.cases if c.contexts]
    if not usable:
        return {"status": "unavailable", "reason": "没有带检索上下文的用例,无法计算 RAG 指标"}

    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import context_precision, context_recall, faithfulness
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": f"ragas 不可用:{type(exc).__name__}: {exc}"}

    metrics = [faithfulness, context_precision]
    skipped: list[str] = []

    embeddings = _build_embeddings()
    if embeddings is None:
        skipped.append("answer_relevancy(需要真实嵌入端点,当前 EMBED_MODE=mock)")
    else:
        from ragas.metrics import answer_relevancy

        metrics.append(answer_relevancy)

    has_ground_truth = all(c.ground_truth for c in usable)
    if has_ground_truth:
        metrics.append(context_recall)
    else:
        skipped.append("context_recall(需要 ground_truth,部分用例缺失)")

    data = {
        "question": [c.question for c in usable],
        "answer": [c.answer for c in usable],
        "contexts": [c.contexts for c in usable],
    }
    if has_ground_truth:
        data["ground_truth"] = [c.ground_truth or "" for c in usable]

    try:
        result = evaluate(
            Dataset.from_dict(data),
            metrics=metrics,
            llm=_build_llm(),
            embeddings=embeddings,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:400]}

    scores: dict[str, float] = {}
    for metric in metrics:
        name = getattr(metric, "name", str(metric))
        try:
            value = float(result[name])
        except Exception:  # noqa: BLE001
            skipped.append(f"{name}(ragas 未返回该指标)")
            continue

        # NaN 必须当成「算不出来」报出来,不能悄悄变成 null ——
        # 否则调用方看到的是「指标存在但没值」,无从判断是数据问题还是解析问题。
        # 实测:faithfulness 在 DeepSeek 上返回 NaN,原因是
        #   "No statements were generated from the answer"
        # —— ragas 的 statement 生成器解析不了该模型的输出格式。
        if math.isnan(value):
            skipped.append(
                f"{name}(ragas 返回 NaN:该指标依赖模型按固定格式输出陈述句,"
                "本模型未产出可解析结果)"
            )
            continue
        scores[name] = round(value, 4)

    return {
        "status": "ok",
        "ragas_version": _ragas_version(),
        "samples": len(usable),
        "scores": scores,
        "skipped": skipped,
    }