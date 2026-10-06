"""Task 9 验收:三个专用 Agent 各自独立,输出结构化,缺证据时如实说。"""

from app.agents.ci_debug_agent import CIDebugAgent
from app.agents.issue_agent import IssueAgent
from app.agents.pr_review_agent import PRReviewAgent
from app.agents.safety_agent import SafetyAgent
from app.schemas.ci import CIDebug
from app.schemas.issue import IssueTriage
from app.schemas.pr import PRReview
from app.schemas.safety import SafetyAssessment


async def test_issue_agent_输出结构化结果(db_with_snapshot, repo_id):
    out = await IssueAgent().run(db_with_snapshot, repo_id=repo_id, number=24)
    assert isinstance(out, IssueTriage)
    assert out.priority == "P0"
    assert out.category == "Bug"
    assert out.action_items
    assert out.rationale


async def test_pr_agent_识别高风险路径并给出决策(db_with_snapshot, repo_id):
    out = await PRReviewAgent().run(db_with_snapshot, repo_id=repo_id, number=12)
    assert isinstance(out, PRReview)
    assert out.decision in ("merge", "hold")
    assert any("auth" in p for p in out.high_risk_paths)
    assert out.missing_checks


async def test_pr_agent_看不到_ci_结论(db_with_snapshot, repo_id):
    """PR Agent 只审改动本身,CI 是否阻塞归 CI Agent —— 分工不能混。"""
    evidence = PRReviewAgent().gather_evidence(db_with_snapshot, repo_id=repo_id, number=12)
    assert "ci" not in evidence
    assert "conclusion" not in evidence


async def test_ci_agent_从日志提取根因与错误块(db_with_snapshot, repo_id):
    out = await CIDebugAgent().run(db_with_snapshot, repo_id=repo_id, number=512)
    assert isinstance(out, CIDebug)
    assert "401" in out.root_cause or any("AssertionError" in b for b in out.error_blocks)
    assert out.error_blocks
    assert out.fix_steps
    assert out.confidence == "high"


async def test_ci_agent_日志缺失时明说而不是编造(db_with_snapshot, repo_id):
    out = await CIDebugAgent().run(db_with_snapshot, repo_id=repo_id, number=99999)
    assert out.confidence == "low"
    assert "未找到" in out.root_cause


async def test_safety_agent_评估写操作(db_with_snapshot, repo_id):
    out = await SafetyAgent().run(db_with_snapshot, action="close_issue", target="issue#3")
    assert isinstance(out, SafetyAssessment)
    assert out.level == "high"
    assert out.draft_only is True


async def test_三个_agent_的_prompt_互不相同():
    prompts = {
        IssueAgent().system_prompt,
        PRReviewAgent().system_prompt,
        CIDebugAgent().system_prompt,
    }
    assert len(prompts) == 3, "退化成一个万能 Prompt 会让专用 Agent 失去意义"


async def test_每个_prompt_都带角色标记():
    from app.core.prompts.roles import parse_role

    assert parse_role(IssueAgent().system_prompt) == "issue_agent"
    assert parse_role(PRReviewAgent().system_prompt) == "pr_review_agent"
    assert parse_role(CIDebugAgent().system_prompt) == "ci_debug_agent"
    assert parse_role(SafetyAgent().system_prompt) == "safety_agent"