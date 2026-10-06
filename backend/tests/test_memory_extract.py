"""记忆沉淀规则:只沉淀证据明确、格式稳定的结论。"""

from dataclasses import dataclass, field

from app.agents.chat_agent import AgentOutcome, ToolCallRecord
from app.core.memory_extract import deposit, extract_candidates


def _outcome(*records: ToolCallRecord) -> AgentOutcome:
    return AgentOutcome(answer="x", stop_reason="completed", steps=1,
                        tool_calls=list(records))


def test_ci_高置信度根因被沉淀():
    outcome = _outcome(ToolCallRecord(
        tool="debug_ci", args={}, step=1,
        data={"number": 512, "confidence": "high", "root_cause": "expected 200 got 401"},
    ))
    items = extract_candidates(outcome)
    assert len(items) == 1
    assert "512" in items[0]["content"]
    assert "401" in items[0]["content"]


def test_ci_低置信度不沉淀():
    outcome = _outcome(ToolCallRecord(
        tool="debug_ci", args={}, step=1,
        data={"number": 999, "confidence": "low", "root_cause": "未找到日志"},
    ))
    assert extract_candidates(outcome) == []


def test_工作流结论被沉淀_有冲突时置信度更低():
    clean = _outcome(ToolCallRecord(tool="run_workflow", args={}, step=1,
                                    data={"conclusion": "可以推进", "conflicts": []}))
    messy = _outcome(ToolCallRecord(tool="run_workflow", args={}, step=1,
                                    data={"conclusion": "暂缓", "conflicts": ["冲突 A"]}))
    assert extract_candidates(clean)[0]["confidence"] > extract_candidates(messy)[0]["confidence"]


def test_失败的工具调用不沉淀():
    outcome = _outcome(ToolCallRecord(tool="debug_ci", args={}, step=1, error="boom",
                                      data={"confidence": "high", "root_cause": "x"}))
    assert extract_candidates(outcome) == []


def test_候选池不是日志_普通只读工具不沉淀():
    outcome = _outcome(
        ToolCallRecord(tool="repo_health", args={}, step=1, data={"open_issues": 4}),
        ToolCallRecord(tool="search_code", args={}, step=1, data={"hits": []}),
    )
    assert extract_candidates(outcome) == []


def test_沉淀进候选池且不重复(db_with_snapshot):
    outcome = _outcome(ToolCallRecord(
        tool="debug_ci", args={}, step=1,
        data={"number": 512, "confidence": "high", "root_cause": "expected 200 got 401"},
    ))
    first = deposit(db_with_snapshot, outcome, repo_id=1, session_id=1, run_id=1)
    assert len(first) == 1
    # 同一条经验第二次跑不应该再进候选池
    second = deposit(db_with_snapshot, outcome, repo_id=1, session_id=2, run_id=2)
    assert second == []


def test_沉淀后状态是待批准而不是已生效(db_with_snapshot):
    outcome = _outcome(ToolCallRecord(
        tool="debug_ci", args={}, step=1,
        data={"number": 512, "confidence": "high", "root_cause": "expected 200 got 401"},
    ))
    created = deposit(db_with_snapshot, outcome, repo_id=1, session_id=1, run_id=1)
    assert created[0].status == "pending", "未批准的候选绝不能直接生效"