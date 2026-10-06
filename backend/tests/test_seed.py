"""Task 4 验收:快照齐备、幂等、且是自洽的一条故事线。"""

from sqlalchemy import func, select

from app.db import models as m
from app.db.seed import load_snapshot


def test_装载快照后数据齐备(db):
    load_snapshot(db)
    assert db.scalar(select(func.count()).select_from(m.Issue)) >= 3
    assert db.scalar(select(func.count()).select_from(m.PullRequest)) >= 1
    assert db.scalar(select(func.count()).select_from(m.CiRun)) >= 1
    assert db.scalar(select(func.count()).select_from(m.Document)) >= 3


def test_装载幂等(db):
    load_snapshot(db)
    n1 = db.scalar(select(func.count()).select_from(m.Issue))
    load_snapshot(db)
    n2 = db.scalar(select(func.count()).select_from(m.Issue))
    assert n1 == n2


def test_快照自洽_pr12_ci512_issue24_同一条故事线(db):
    load_snapshot(db)
    pr = db.scalar(select(m.PullRequest).where(m.PullRequest.number == 12))
    ci = db.scalar(select(m.CiRun).where(m.CiRun.number == 512))
    issue = db.scalar(select(m.Issue).where(m.Issue.number == 24))

    assert pr is not None and ci is not None and issue is not None
    # PR 关联到 Issue #24
    assert 24 in pr.related_issues
    # PR 分支 == CI 分支
    assert ci.branch == pr.head_ref
    # 三个对象讲的是同一件事:登录
    assert "登录" in issue.title
    assert "登录" in pr.title
    # CI 日志必须真的存在且含关键错误
    log = open(ci.log_path, encoding="utf-8").read()
    assert "AssertionError" in log
    assert "expected 200 got 401" in log
    assert "src/auth/session.py:88" in log


def test_高风险文件被标记(db):
    load_snapshot(db)
    files = db.scalars(select(m.PrFile)).all()
    assert any(f.is_high_risk and "auth" in f.path for f in files)
    # 文档类改动不应被误标
    doc_file = [f for f in files if f.path == "docs/api.md"]
    assert doc_file and doc_file[0].is_high_risk is False


def test_失败与成功_ci_都存在(db):
    load_snapshot(db)
    conclusions = {c.number: c.conclusion for c in db.scalars(select(m.CiRun)).all()}
    assert conclusions[512] == "failure"
    assert conclusions[511] == "success"