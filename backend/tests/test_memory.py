"""Task 12 验收(记忆部分):未批准不召回,批准后可召回,跨仓库隔离。"""

from app.core.memory import MemHub


def test_候选未批准不参与召回(db_with_snapshot):
    hub = MemHub()
    hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                         content="clowder-ai 的 CI 需要先跑 migrate", confidence=0.8)
    assert hub.recall(db_with_snapshot, repo_id=1, query="CI migrate", top_k=5) == []


def test_批准后进入召回且标记来源(db_with_snapshot):
    hub = MemHub()
    candidate = hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                                     content="clowder-ai 的 CI 需要先跑 migrate", confidence=0.8)
    hub.approve(db_with_snapshot, candidate.id, approved_by="member")

    hits = hub.recall(db_with_snapshot, repo_id=1, query="CI migrate", top_k=5)
    assert hits
    assert hits[0].source == "memory", "记忆证据要与文档证据区分开"
    assert hits[0].approved_by == "member"


def test_记忆按仓库隔离(db_with_snapshot):
    hub = MemHub()
    candidate = hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                                     content="只属于仓库 1 的经验", confidence=1.0)
    hub.approve(db_with_snapshot, candidate.id, approved_by="member")
    assert hub.recall(db_with_snapshot, repo_id=2, query="仓库 1 经验", top_k=5) == []


def test_重复批准幂等(db_with_snapshot):
    hub = MemHub()
    candidate = hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                                     content="x", confidence=1.0)
    first = hub.approve(db_with_snapshot, candidate.id, approved_by="member")
    second = hub.approve(db_with_snapshot, candidate.id, approved_by="member")
    assert first.id == second.id


def test_被拒绝的候选不参与召回(db_with_snapshot):
    hub = MemHub()
    candidate = hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                                     content="错误结论:CI 不用跑测试", confidence=0.9)
    hub.reject(db_with_snapshot, candidate.id)
    assert hub.recall(db_with_snapshot, repo_id=1, query="CI 测试", top_k=5) == []


def test_候选池与已生效列表分开(db_with_snapshot):
    hub = MemHub()
    hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                         content="待确认经验", confidence=0.5)
    assert len(hub.pending(db_with_snapshot, 1)) == 1
    assert hub.approved(db_with_snapshot, 1) == []

def test_纯中文记忆能被召回(db_with_snapshot):
    """回归测试。

    记忆召回曾经用 `text.split()` 分词 —— 中文没有空格,整句变成一个词项,
    于是「登录接口变更」匹配不上「登录接口的变更说明」,中文记忆基本召不回。
    当时验收能过,只是因为候选内容里恰好带了 "CI"、"#512" 这类 ASCII。
    """
    hub = MemHub()
    candidate = hub.record_candidate(
        db_with_snapshot, repo_id=1, session_id=1, run_id=1,
        content="登录接口的变更说明:token 过期后必须先清理旧会话", confidence=0.8)
    hub.approve(db_with_snapshot, candidate.id, approved_by="member")

    hits = hub.recall(db_with_snapshot, repo_id=1, query="登录接口变更", top_k=5)
    assert hits, "纯中文记忆必须能被召回(靠双字切分,而不是空格分词)"
    assert "登录" in hits[0].content


def test_中文记忆的排序按命中词项数(db_with_snapshot):
    hub = MemHub()
    for text in ("登录接口的变更说明", "接口文档更新", "数据库迁移注意事项"):
        c = hub.record_candidate(db_with_snapshot, repo_id=1, session_id=1, run_id=1,
                                 content=text, confidence=0.5)
        hub.approve(db_with_snapshot, c.id, approved_by="member")

    hits = hub.recall(db_with_snapshot, repo_id=1, query="登录接口变更", top_k=5)
    assert hits[0].content == "登录接口的变更说明", "命中词项最多的应排第一"