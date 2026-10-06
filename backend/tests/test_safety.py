"""Task 13 验收:写操作闸门。"""

import pytest

from app.db import models as m
from app.safety import drafts, policy
from app.safety.audit import AuditLog
from app.tools import registry


def test_注册表不存在_execute_action():
    assert "execute_action" not in registry.REGISTRY
    assert [n for n, s in registry.REGISTRY.items() if s.is_write] == ["draft_action"]


def test_白名单外的动作被拒绝(db_with_snapshot):
    with pytest.raises(policy.PermissionDenied):
        policy.assert_can_write("maintainer", "delete_repository")


def test_未知角色被拒绝(db_with_snapshot):
    with pytest.raises(policy.PermissionDenied):
        policy.assert_can_write("hacker", "close_issue")


def test_viewer_不能确认草稿(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="close_issue",
                          target="issue#3", payload={}, role="member")
    with pytest.raises(policy.PermissionDenied):
        drafts.confirm(db_with_snapshot, draft.id, role="viewer")
    db_with_snapshot.refresh(draft)
    assert draft.status == "pending", "越权失败不得改变状态"


def test_越权尝试也要留审计(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="close_issue",
                          target="issue#3", payload={}, role="member")
    with pytest.raises(policy.PermissionDenied):
        drafts.confirm(db_with_snapshot, draft.id, role="viewer")
    logs = db_with_snapshot.query(AuditLog).all()
    assert any(entry.result == "denied" for entry in logs), "403 也必须留痕"


def test_确认后才执行且写审计(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="comment_on_issue",
                          target="issue#3", payload={"body": "进展如何?"}, role="member")
    assert draft.status == "pending"
    before = db_with_snapshot.query(AuditLog).count()

    done = drafts.confirm(db_with_snapshot, draft.id, role="member")
    assert done.status == "executed"
    assert db_with_snapshot.query(AuditLog).count() == before + 1
    assert db_with_snapshot.query(AuditLog).filter_by(result="executed").count() == 1

    # 副作用真的发生了:评论被追加到 Issue 正文
    issue = db_with_snapshot.query(m.Issue).filter_by(repo_id=1, number=3).one()
    assert "进展如何?" in issue.body


def test_关闭_issue_改变状态(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="close_issue",
                          target="issue#3", payload={}, role="member")
    drafts.confirm(db_with_snapshot, draft.id, role="member")
    issue = db_with_snapshot.query(m.Issue).filter_by(repo_id=1, number=3).one()
    assert issue.state == "closed"


def test_拒绝后不执行(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="close_issue",
                          target="issue#3", payload={}, role="member")
    result = drafts.reject(db_with_snapshot, draft.id, role="member")
    assert result.status == "rejected"
    assert db_with_snapshot.query(AuditLog).filter_by(result="rejected").count() == 1
    issue = db_with_snapshot.query(m.Issue).filter_by(repo_id=1, number=3).one()
    assert issue.state == "open", "拒绝后不得有任何副作用"


def test_非法状态迁移被拒(db_with_snapshot):
    draft = drafts.create(db_with_snapshot, repo_id=1, run_id=1, action="close_issue",
                          target="issue#3", payload={}, role="member")
    drafts.reject(db_with_snapshot, draft.id, role="member")
    with pytest.raises(drafts.InvalidTransition):
        drafts.confirm(db_with_snapshot, draft.id, role="member")


def test_高风险动作被标记():
    assert policy.risk_level("close_issue") == "high"
    assert policy.risk_level("comment_on_issue") == "low"


def test_不存在的草稿报错(db_with_snapshot):
    with pytest.raises(drafts.DraftNotFound):
        drafts.confirm(db_with_snapshot, 999999, role="member")

# --------------------------------------------------------------------------- 仓库级安全检查


def test_check_repo_干净仓库是低风险(db_with_snapshot, repo_id):
    from app.agents.safety_agent import SafetyAgent
    from app.db import models as m
    from app.db.models import DraftStatus

    # 构造真正干净的状态:待确认草稿、越权审计、高风险路径全部清掉。
    # 快照里 PR #12 本身就触及 src/auth/**,不清掉的话风险等级不会是 low。
    db_with_snapshot.query(m.ActionDraft).filter_by(
        repo_id=repo_id, status=DraftStatus.PENDING.value
    ).delete()
    db_with_snapshot.query(m.AuditLog).delete()
    db_with_snapshot.query(m.PrFile).filter_by(is_high_risk=True).delete()
    db_with_snapshot.commit()

    out = SafetyAgent().check_repo(db_with_snapshot, repo_id)
    assert out.level == "low"
    assert out.draft_only is True


def test_check_repo_待确认草稿会抬高关注度(db_with_snapshot, repo_id):
    from app.agents.safety_agent import SafetyAgent
    from app.db import models as m

    db_with_snapshot.add(m.ActionDraft(repo_id=repo_id, action="comment_issue",
                                       target="issue#3", preview="草稿", status="pending"))
    db_with_snapshot.commit()

    out = SafetyAgent().check_repo(db_with_snapshot, repo_id)
    assert out.level in ("medium", "high")
    assert any("尚未确认" in r for r in out.reasons)


def test_check_repo_越权审计直接判高风险(db_with_snapshot, repo_id):
    from app.agents.safety_agent import SafetyAgent
    from app.db import models as m

    db_with_snapshot.add(m.AuditLog(action="comment_issue", target="issue#3",
                                    result="denied", actor_role="viewer", detail="越权"))
    db_with_snapshot.commit()

    out = SafetyAgent().check_repo(db_with_snapshot, repo_id)
    assert out.level == "high"
    assert any("越权" in r for r in out.reasons)


def test_check_repo_高风险路径会被点名(db_with_snapshot, repo_id):
    from sqlalchemy import select

    from app.agents.safety_agent import SafetyAgent
    from app.db import models as m

    pr = db_with_snapshot.scalar(select(m.PullRequest).where(m.PullRequest.repo_id == repo_id))
    db_with_snapshot.add(m.PrFile(pr_id=pr.id, path=".github/workflows/ci.yml",
                                  is_high_risk=True, additions=5, deletions=1))
    db_with_snapshot.commit()

    out = SafetyAgent().check_repo(db_with_snapshot, repo_id)
    assert out.level in ("medium", "high")
    assert any(".github/workflows/ci.yml" in r for r in out.reasons)