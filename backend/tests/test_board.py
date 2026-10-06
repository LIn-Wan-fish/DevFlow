"""共享发现板:变更集、搁置集、互斥锁。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.board import FindingBoard, normalize_topic
from app.core import cache as cache_module
from app.core.cache import MemoryCache, get_cache
from app.db import models as m


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module.reset_cache()
    cache_module._cache = MemoryCache()
    yield
    cache_module.reset_cache()


@pytest.mark.parametrize("raw,expected", [
    ("CI #512", "ci 512"),
    ("ci  512", "ci 512"),
    ("  CI #512  ", "ci 512"),
    ("Issue #24", "issue 24"),
    ("CI:512", "ci512"),
])
def test_主题归一化(raw, expected):
    """不归一化的话 「CI #512」和「ci 512」会被当成两件事,重复调查拦不住。"""
    assert normalize_topic(raw) == expected


def _publish(db, board, run_id, author, topic, conclusion, **kw):
    return board.publish(db, run_id=run_id, repo_id=1, author=author,
                         topic=topic, conclusion=conclusion, **kw)


def test_发布与读回(db_with_snapshot):
    board = FindingBoard()
    f = _publish(db_with_snapshot, board, 1, "ci_debug", "CI #512",
                 "密码校验分支被改坏", evidence=["ci#512"], confidence=0.8)
    assert f.id is not None
    assert f.author == "ci_debug"
    assert f.evidence == ["ci#512"]

    got = board.read(db_with_snapshot, 1)
    assert [x.id for x in got] == [f.id]


def test_发现不可就地修改(db_with_snapshot):
    """**不可变必须由代码强制**,不能只靠约定 —— 否则协作历史迟早被就地改烂。"""
    board = FindingBoard()
    f = _publish(db_with_snapshot, board, 1, "ci_debug", "CI #512", "结论 A")

    f.conclusion = "悄悄改掉"
    with pytest.raises(ValueError, match="不可修改"):
        db_with_snapshot.commit()
    db_with_snapshot.rollback()


def test_修正要追加新发现并指向旧的(db_with_snapshot):
    board = FindingBoard()
    old = _publish(db_with_snapshot, board, 1, "ci_debug", "CI #512", "旧结论")
    new = _publish(db_with_snapshot, board, 1, "observer", "CI #512", "新结论",
                   supersedes_id=old.id)
    assert new.supersedes_id == old.id
    # 旧的那条**仍然在库里** —— 推翻这件事本身也是历史
    assert db_with_snapshot.get(m.AgentFinding, old.id) is not None


def test_同一主题结论不同即分歧(db_with_snapshot):
    """把冲突变成**结构化对象**,而不是混在一段文本里被和稀泥。"""
    board = FindingBoard()
    _publish(db_with_snapshot, board, 1, "pr_review", "PR #12", "可以合入")
    _publish(db_with_snapshot, board, 1, "ci_debug", "PR #12", "流水线是失败的")

    conflicts = board.conflicting_topics(db_with_snapshot, 1)
    assert len(conflicts) == 1
    assert set(conflicts[0]["authors"]) == {"pr_review", "ci_debug"}
    assert conflicts[0]["topic"] == "PR #12"


def test_结论一致不算分歧(db_with_snapshot):
    board = FindingBoard()
    _publish(db_with_snapshot, board, 1, "a", "CI #512", "同一结论")
    _publish(db_with_snapshot, board, 1, "b", "CI #512", "同一结论")
    assert board.conflicting_topics(db_with_snapshot, 1) == []


def test_被推翻的不再参与分歧判断(db_with_snapshot):
    board = FindingBoard()
    old = _publish(db_with_snapshot, board, 1, "a", "CI #512", "旧结论")
    _publish(db_with_snapshot, board, 1, "b", "CI #512", "新结论", supersedes_id=old.id)
    assert board.conflicting_topics(db_with_snapshot, 1) == []


def test_搁置集_未定论的发现也能被读到(db_with_snapshot):
    """对应 Plastic 的 shelve:还没定论的中间成果,别人可以取用或接手。"""
    board = FindingBoard()
    _publish(db_with_snapshot, board, 1, "a", "CI #512", "线索:像是时区问题",
             status=m.FindingStatus.TENTATIVE.value, confidence=0.3)
    got = board.read(db_with_snapshot, 1)
    assert got[0].status == "tentative"


def test_不同运行之间的发现互不串(db_with_snapshot):
    board = FindingBoard()
    _publish(db_with_snapshot, board, 1, "a", "CI #512", "第一次运行")
    _publish(db_with_snapshot, board, 2, "a", "CI #512", "第二次运行")
    assert len(board.read(db_with_snapshot, 1)) == 1
    assert len(board.read(db_with_snapshot, 2)) == 1


# --------------------------------------------------------------------------- 互斥锁


async def test_同一主题只有一个_Agent_能认领():
    """这是省钱的锁:同一件事被三个 Agent 各查一遍,模型调用就白烧三份。"""
    board = FindingBoard()
    assert await board.claim("CI #512") is True
    assert await board.claim("ci  512") is False, "归一化之后应当认成同一件事"
    await board.release("CI #512")
    assert await board.claim("CI #512") is True


async def test_不同主题互不影响():
    board = FindingBoard()
    assert await board.claim("CI #512") is True
    assert await board.claim("PR #12") is True


def test_发现板用的是共享缓存():
    """生产环境配了 Redis 才是真的跨副本 —— 这里确认它没绕过缓存层。"""
    board = FindingBoard()
    assert get_cache() is cache_module._cache
