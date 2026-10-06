"""Task 3 验收:模型可建、关系可串、状态机有约束、高风险判定集中在一处。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.base import Base


@pytest.fixture
def fresh_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def test_全表可建且轨迹四级能串起来(fresh_db):
    repo = m.Repo(owner="acme", name="clowder-ai", default_branch="main")
    fresh_db.add(repo)
    fresh_db.flush()
    run = m.AgentRun(repo_id=repo.id, question="q", status="running", mode="mock")
    fresh_db.add(run)
    fresh_db.flush()
    wf = m.WorkflowRun(agent_run_id=run.id, question="q", status="running", replan_count=0)
    fresh_db.add(wf)
    fresh_db.flush()
    task = m.TaskRun(workflow_run_id=wf.id, task_key="t1", agent="issue_agent",
                     title="t", depends_on=[], status="pending")
    fresh_db.add(task)
    fresh_db.flush()
    fresh_db.add(m.ToolCall(agent_run_id=run.id, task_run_id=task.id, tool="analyze_issue",
                            args={"number": 24}, result_summary="ok"))
    fresh_db.commit()
    assert fresh_db.query(m.ToolCall).one().agent_run_id == run.id


def test_draft_非法状态被拦住(fresh_db):
    d = m.ActionDraft(repo_id=1, action="close_issue", target="issue#3", payload={},
                      preview="", risk_level="high", status="pending",
                      requested_by_role="member")
    fresh_db.add(d)
    fresh_db.commit()
    assert d.status == "pending"
    with pytest.raises(ValueError):
        d.status = "executed_without_confirmation"
        fresh_db.flush()


def test_issue_非法状态被拦住(fresh_db):
    i = m.Issue(repo_id=1, number=1, title="t", state="open")
    fresh_db.add(i)
    fresh_db.commit()
    with pytest.raises(ValueError):
        i.state = "somehow"


def test_高风险路径判定集中在一处():
    from app.safety.policy import HIGH_RISK_PATHS, is_high_risk_path

    assert is_high_risk_path("src/auth/login.py") is True
    assert is_high_risk_path("src\\auth\\session.py") is True
    assert is_high_risk_path(".github/workflows/ci.yml") is True
    assert is_high_risk_path("src/ui/Button.tsx") is False
    assert is_high_risk_path("docs/readme.md") is False
    assert ".github/workflows/**" in HIGH_RISK_PATHS


def test_仓库唯一约束(fresh_db):
    fresh_db.add(m.Repo(owner="a", name="b"))
    fresh_db.commit()
    fresh_db.add(m.Repo(owner="a", name="b"))
    with pytest.raises(Exception):
        fresh_db.commit()

# --------------------------------------------------------------------------- CI 失败语义


def test_非正常结束的结论都算失败():
    """回归:全项目曾有 5 处写的是 `conclusion == "failure"`。

    真实数据里用户仓库 6 次运行**全是 startup_failure**,系统却报「没有失败 CI」,
    Observer 甚至据此说「所有 CI 均通过」。判断必须是「不在正常集合里」,
    而不是名单式地只认 failure —— 后者在 GitHub 新增结论时会静默漏掉。
    """
    from app.github.conclusions import HEALTHY_CONCLUSIONS, is_failed_conclusion

    for bad in ("failure", "startup_failure", "timed_out", "cancelled", "action_required"):
        assert is_failed_conclusion(bad), f"{bad} 必须算失败"

    for ok in ("success", "skipped", "neutral", "SUCCESS", " Success "):
        assert not is_failed_conclusion(ok), f"{ok} 不应算失败"
        assert ok.strip().lower() in HEALTHY_CONCLUSIONS


def test_总览统计把_startup_failure_算作失败(client, db_with_snapshot, repo_id):
    from app.db import models as m

    before = client.get(f"/api/repos/{repo_id}/health").json()["failed_ci"]
    db_with_snapshot.add(m.CiRun(repo_id=repo_id, number=999001, workflow="Pages",
                                 branch="master", status="completed",
                                 conclusion="startup_failure"))
    db_with_snapshot.commit()

    after = client.get(f"/api/repos/{repo_id}/health").json()["failed_ci"]
    assert after == before + 1, "startup_failure 必须计入失败 CI"


def test_冲突判定不把_startup_failure_当成通过():
    from app.core.workflow_rules import collect_facts, detect_conflicts

    facts = collect_facts([
        {"agent": "pr_review_agent", "number": 12, "decision": "hold", "risk_level": "low"},
        {"agent": "ci_debug_agent", "number": 512, "conclusion": "startup_failure"},
    ])
    conflicts = detect_conflicts(facts)
    assert not any("所有 CI 均通过" in c for c in conflicts), \
        "startup_failure 不能被当成 CI 通过"