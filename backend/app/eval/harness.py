"""评测执行器。

关键点:走的**就是线上那条链**(ChatAgent + 工具 + 工作流),不另写简化逻辑 ——
否则评测通过不代表线上没问题,这个评测就没有回归价值。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.chat_agent import ChatAgent
from app.config import settings
from app.db import models as m
from app.eval import ragas_runner
from app.eval.rules import Trace, check

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    key: str
    question: str
    passed: bool
    rule_results: list[dict] = field(default_factory=list)
    actual: dict = field(default_factory=dict)


@dataclass
class EvalOutcome:
    eval_run_id: int
    total: int
    passed: int
    failed: int
    cases: list[CaseResult] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "eval_run_id": self.eval_run_id,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "metrics": self.metrics,
            "cases": [
                {"key": c.key, "question": c.question, "passed": c.passed,
                 "rule_results": c.rule_results, "actual": c.actual}
                for c in self.cases
            ],
        }


def _executed_write_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(m.AuditLog).where(m.AuditLog.result == "executed")
    ) or 0


async def run_eval(db: Session, dataset_path: str | Path, mode: str = "mock",
                   repo_id: int = 1) -> EvalOutcome:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))

    run = m.EvalRun(dataset=str(dataset_path), mode=mode, total=len(cases))
    db.add(run)
    db.commit()

    results: list[CaseResult] = []
    for case in cases:
        events: list[str] = []

        def emit(kind, data, sink=events):  # noqa: ANN001
            sink.append(kind)

        before = _executed_write_count(db)
        try:
            outcome = await ChatAgent().run(
                db, repo_id=repo_id, question=case["question"], history=[], emit=emit,
            )
        except Exception as exc:  # noqa: BLE001
            # 一条用例炸了**不能**让整轮评测 500 并丢掉前面所有结果 ——
            # 实测踩到过:Synthesis 结构化输出连续两次解析失败,整个 /api/eval/run 抛 500。
            # 评测的执行器不该比被测对象更脆。如实记成失败并继续。
            logger.exception("评测用例执行失败 key=%s", case["key"])
            detail = f"{type(exc).__name__}: {exc}"
            db.add(m.EvalCase(
                eval_run_id=run.id, case_key=case["key"], question=case["question"],
                expected=case.get("expect") or {},
                actual={"error": detail},
                rule_results=[{"rule": "agent_error", "passed": False, "detail": detail}],
                passed=False,
            ))
            db.commit()
            results.append(CaseResult(
                key=case["key"], question=case["question"], passed=False,
                rule_results=[{"rule": "agent_error", "passed": False, "detail": detail}],
                actual={"error": detail},
            ))
            continue
        after = _executed_write_count(db)

        writes = ["executed"] * (after - before)
        trace = Trace(
            tool_names=[record.tool for record in outcome.tool_calls],
            events=events,
            executed_writes=writes,
            answer=outcome.answer,
            stop_reason=outcome.stop_reason,
            citations=outcome.citations,
            agent_outputs=[record.data for record in outcome.tool_calls],
        )
        rule_results = check(case, trace)
        passed = all(r.passed for r in rule_results)

        db.add(m.EvalCase(
            eval_run_id=run.id, case_key=case["key"], question=case["question"],
            expected=case.get("expect") or {},
            actual={"answer": outcome.answer, "tools": trace.tool_names,
                    "stop_reason": outcome.stop_reason},
            rule_results=[{"rule": r.rule, "passed": r.passed, "detail": r.detail}
                          for r in rule_results],
            passed=passed,
        ))
        results.append(CaseResult(
            key=case["key"], question=case["question"], passed=passed,
            rule_results=[{"rule": r.rule, "passed": r.passed, "detail": r.detail}
                          for r in rule_results],
            actual={"answer": outcome.answer, "tools": trace.tool_names,
                    "stop_reason": outcome.stop_reason},
        ))

    passed_count = sum(1 for c in results if c.passed)

    # 内置评测集(tests/data/eval_cases.json)是**针对快照数据**写的:
    # 里面引用的 Issue #24 / PR #12 / CI #512 与快照语料,在真实 GitHub 仓库里不存在。
    # 在 github 模式下跑它只会得到一堆「数据缺失」的失败,看不出是模式问题,
    # 所以显式提示一句。
    if settings.data_source != "snapshot":
        metrics["eval_dataset_note"] = (
            f"当前 DATA_SOURCE={settings.data_source},而内置评测集是针对快照数据编写的;"
            "这些失败大概率是模式不匹配,不是系统缺陷。"
        )
    # RAGAS 走独立评测容器;拿不到就如实报告 unavailable
    metrics = await ragas_runner.run(db, repo_id, mode)

    run.passed = passed_count
    run.failed = len(results) - passed_count
    run.metrics = metrics
    db.commit()

    return EvalOutcome(eval_run_id=run.id, total=len(results), passed=passed_count,
                       failed=len(results) - passed_count, cases=results, metrics=metrics)


def history(db: Session, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(m.EvalRun).order_by(m.EvalRun.id.desc()).limit(limit)).all()
    return [
        {"id": r.id, "dataset": r.dataset, "mode": r.mode, "total": r.total,
         "passed": r.passed, "failed": r.failed, "metrics": r.metrics,
         "started_at": r.started_at.isoformat() if r.started_at else None}
        for r in rows
    ]