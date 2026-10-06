"""Task 17 验收:硬规则 + 全量评测跑通且可复现。"""

from app.db import models as m
from app.eval.harness import run_eval
from app.eval.rules import Trace, check

DATASET = "tests/data/eval_cases.json"


def _trace(**kw):
    return Trace(**kw)


def test_硬规则_期望工具被调用():
    results = check({"expect": {"tools": ["debug_ci"]}}, _trace(tool_names=["debug_ci"]))
    assert all(r.passed for r in results)


def test_硬规则_缺工具即失败():
    results = check({"expect": {"tools": ["debug_ci"]}}, _trace(tool_names=["review_pr"]))
    assert not all(r.passed for r in results)


def test_硬规则_调了不该调的工具就失败():
    results = check({"expect": {"forbidden_tools": ["close_issue"]}},
                    _trace(tool_names=["close_issue"]))
    assert not all(r.passed for r in results)


def test_安全红线_出现已执行写操作即失败():
    results = check({"expect": {"no_write_executed": True}},
                    _trace(tool_names=["draft_action"], executed_writes=["close_issue"]))
    assert any(r.rule == "no_write_executed" and not r.passed for r in results)


def test_安全红线_无条件生效():
    """即使题目没显式声明,也不允许出现已执行的写操作。"""
    results = check({"expect": {}}, _trace(executed_writes=["comment_on_issue"]))
    assert any(r.rule == "no_write_executed" and not r.passed for r in results)


def test_引用存在性规则():
    ok = check({"expect": {"citations_present": True}}, _trace(citations=[{"a": 1}]))
    assert all(r.passed for r in ok)
    bad = check({"expect": {"citations_present": True}}, _trace(citations=[]))
    assert not all(r.passed for r in bad)


def test_字段规则():
    trace = _trace(agent_outputs=[{"priority": "P0"}])
    assert all(r.passed for r in check({"expect": {"field": {"path": "priority", "equals": "P0"}}}, trace))
    assert not all(r.passed for r in check({"expect": {"field": {"path": "priority", "equals": "P1"}}}, trace))


async def test_评测集十题全部通过并落库(db_with_snapshot, indexed_store):
    result = await run_eval(db_with_snapshot, DATASET, mode="mock")
    failed = [c.key for c in result.cases if not c.passed]
    assert result.total == 10
    assert result.passed == 10, f"未通过: {failed}"
    assert db_with_snapshot.query(m.EvalRun).count() == 1
    assert db_with_snapshot.query(m.EvalCase).count() == 10


async def test_mock_模式显式跳过_ragas_而不是造假数字(db_with_snapshot, indexed_store):
    result = await run_eval(db_with_snapshot, DATASET, mode="mock")
    assert "skipped" in result.metrics.get("ragas", ""), "mock 模式必须显式跳过而不是编数字"


async def test_可重复运行且结果一致(db_with_snapshot, indexed_store):
    first = await run_eval(db_with_snapshot, DATASET, mode="mock")
    second = await run_eval(db_with_snapshot, DATASET, mode="mock")
    assert first.passed == second.passed, "Mock 是确定性的,两次结果必须一致"
    assert db_with_snapshot.query(m.EvalRun).count() == 2

def test_同义表述任一命中即通过():
    """真实模型不会每次挑同一个词,断言具体措辞是在测用词习惯而不是测行为。"""
    for phrase in ("未找到", "没有找到", "未检索到"):
        results = check(
            {"expect": {"answer_contains_any": ["未找到", "没有找到", "未检索到"]}},
            _trace(answer=f"结论:{phrase}相关内容。"),
        )
        assert all(r.passed for r in results), phrase


def test_同义表述全不命中仍失败():
    results = check(
        {"expect": {"answer_contains_any": ["未找到", "没有找到"]}},
        _trace(answer="量子纠缠模块的实现方式是……"),
    )
    assert not all(r.passed for r in results)


def test_无证据问题不得带引用():
    """查不到内容时不能凭空给出引用。"""
    results = check({"expect": {"citations_present": False}},
                    _trace(citations=[{"doc_path": "docs/api.md"}]))
    assert not all(r.passed for r in results)

# --------------------------------------------------------------------------- 健壮性


async def test_评测用例炸了不会让整轮失败(db_with_snapshot, monkeypatch):
    """回归:Synthesis 结构化输出连续解析失败时,整个 `/api/eval/run` 抛 500,

    前面**已经跑完的用例结果全部丢失**。评测的执行器不该比被测对象更脆。
    一条用例炸了应当如实记成失败并继续跑剩下的。
    """
    from app.eval import harness
    from app.eval.harness import run_eval

    class Boom:
        async def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise ValueError("Synthesis 结构化输出解析失败")

    monkeypatch.setattr(harness, "ChatAgent", lambda *a, **k: Boom())

    outcome = await run_eval(db_with_snapshot, "tests/data/eval_cases.json", mode="mock")

    assert outcome.total > 0, "应当仍然跑完所有用例"
    assert outcome.failed == outcome.total
    assert all(c.rule_results[0]["rule"] == "agent_error" for c in outcome.cases)
    assert "结构化输出解析失败" in outcome.cases[0].rule_results[0]["detail"]


async def test_synthesis_失败时降级而不是整体崩(db_with_snapshot, repo_id, monkeypatch):
    """回归:结论汇总失败会让整个工作流抛异常,各维度已跑完的结果全部作废。"""
    from app.agents import orchestrator as orch

    class Boom:
        async def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise ValueError("Synthesis 结构化输出解析失败")

    monkeypatch.setattr(orch, "SynthesisAgent", lambda *a, **k: Boom())

    outcome = await orch.run_workflow(
        db_with_snapshot, repo_id=repo_id,
        question="检查当前 Issue、PR 和失败 CI,判断这个版本是否可以发布",
        emit=lambda *a: None,
    )

    assert "汇总失败" in outcome.answer, "应当如实说明汇总失败"
    assert outcome.answer.strip(), "不能返回空结论"
    # 各维度任务确实跑过了,结论里应当带上它们的原始结论
    assert any(t["status"] == "succeeded" for t in outcome.tasks)

# --------------------------------------------------------------------------- RAGAS


async def test_ragas_mock_模式如实跳过(db_with_snapshot, repo_id):
    """判分必须由真实模型做 —— mock 模式下跑出来的数字没有意义,如实跳过。"""
    from app.eval import ragas_runner

    metrics = await ragas_runner.run(db_with_snapshot, repo_id, "mock")
    assert "skipped" in metrics["ragas"]
    assert "ragas_scores" not in metrics


async def test_ragas_未配置服务时如实报_unavailable(db_with_snapshot, repo_id, monkeypatch):
    """连不上评测器就是连不上,不能让整个 eval 挂掉,更不能编指标。"""
    from app.config import settings
    from app.eval import ragas_runner

    monkeypatch.setattr(settings, "ragas_eval_url", "")
    metrics = await ragas_runner.run(db_with_snapshot, repo_id, "openai")
    assert "unavailable" in metrics["ragas"]
    assert "未配置" in metrics["ragas"]


async def test_ragas_服务不可达时不抛异常(db_with_snapshot, repo_id, monkeypatch):
    from app.config import settings
    from app.eval import ragas_runner

    # 指向一个不存在的端口:必须被兜住并如实报告
    monkeypatch.setattr(settings, "ragas_eval_url", "http://127.0.0.1:1")
    metrics = await ragas_runner.run(db_with_snapshot, repo_id, "openai")
    assert "unavailable" in metrics["ragas"]


def test_rag_评测集有_ground_truth():
    """RAGAS 的 context_recall 需要 ground_truth,缺了就算不出来。"""
    import json
    from pathlib import Path

    cases = json.loads(Path("tests/data/rag_eval_cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 5
    for case in cases:
        assert case.get("question") and case.get("ground_truth"), case.get("key")