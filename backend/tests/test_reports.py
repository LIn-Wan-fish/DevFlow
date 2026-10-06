"""自动周报:生成、幂等、调度、API。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import models as m
from app.reports import scheduler, service


def test_周期标识按_iso_周():
    """用 ISO 周做幂等键:同一周无论检查多少次都只该有一份。"""
    monday = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
    sunday = datetime(2026, 10, 11, 23, 0, tzinfo=UTC)
    next_monday = datetime(2026, 10, 12, 0, 30, tzinfo=UTC)

    assert service.current_period_key(monday) == "2026-W41"
    # 同一周内不同时刻必须是同一个键,否则幂等就失效了
    assert service.current_period_key(sunday) == "2026-W41"
    assert service.current_period_key(next_monday) == "2026-W42"


def test_生成周报并统计正确(db_with_snapshot, repo_id):
    report = service.generate(db_with_snapshot, repo_id, trigger="manual")

    assert report.period_key == service.current_period_key()
    assert report.trigger == "manual"
    assert report.path.startswith("docs/weekly-")
    # 快照里 4 个 open issue / 1 个已合并 PR / 1 次失败 CI
    assert report.open_issues == 4
    assert report.merged_prs == 1
    assert report.failed_ci == 1
    assert "## 概况" in report.body and "## 风险提示" in report.body


def test_同一周期幂等不会重复生成(db_with_snapshot, repo_id):
    first = service.generate(db_with_snapshot, repo_id)
    second = service.generate(db_with_snapshot, repo_id, trigger="manual")

    assert first.id == second.id, "同一周期必须返回同一份"
    rows = db_with_snapshot.scalars(
        select(m.WeeklyReport).where(m.WeeklyReport.repo_id == repo_id)
    ).all()
    assert len(rows) == 1


def test_is_due_生成前后相反(db_with_snapshot, repo_id):
    assert service.is_due(db_with_snapshot, repo_id) is True
    service.generate(db_with_snapshot, repo_id)
    assert service.is_due(db_with_snapshot, repo_id) is False


def test_跨周期会生成新的一份(db_with_snapshot, repo_id):
    """幂等不能变成「永远只有一份」—— 下一周必须能出新周报。"""
    this_week = service.generate(db_with_snapshot, repo_id,
                                 now=datetime(2026, 10, 6, tzinfo=UTC))
    next_week = service.generate(db_with_snapshot, repo_id,
                                 now=datetime(2026, 10, 13, tzinfo=UTC))

    assert this_week.id != next_week.id
    assert this_week.period_key == "2026-W41"
    assert next_week.period_key == "2026-W42"


def test_回写知识库(db_with_snapshot, repo_id):
    """文章的亮点 7 要求周报**回写知识库**,让历史产出变成可检索资产。"""
    report = service.generate(db_with_snapshot, repo_id)
    doc = db_with_snapshot.scalar(
        select(m.Document).where(m.Document.repo_id == repo_id,
                                 m.Document.path == report.path)
    )
    assert doc is not None, "周报必须回写成 Document,否则检索不到"


def test_调度器只补缺的_不重复(db_with_snapshot, repo_id):
    import contextlib

    @contextlib.contextmanager
    def factory():
        # 复用测试会话,且不要在退出时关掉它 —— 后面还要再用一次
        yield db_with_snapshot

    assert scheduler.check_once(factory) == 1, "首次检查应当补一份"
    assert scheduler.check_once(factory) == 0, "已存在就不该再生成"


def test_工具与服务共用同一份逻辑(db_with_snapshot, repo_id):
    """回归:统计逻辑只能有一处。

    这个项目吃过亏 —— CI 失败判定曾在 6 个地方各写一遍,漏掉 startup_failure。
    """
    from app.tools.registry import ToolContext, execute

    ctx = ToolContext(db=db_with_snapshot, repo_id=repo_id)
    import asyncio

    result = asyncio.run(execute("weekly_report", {}, ctx))
    report = db_with_snapshot.scalar(
        select(m.WeeklyReport).where(m.WeeklyReport.repo_id == repo_id)
    )
    assert result.data["report_id"] == report.id
    assert result.data["open_issues"] == report.open_issues


# --------------------------------------------------------------------------- API


def test_周报接口_列表与详情(client, db_with_snapshot, repo_id):
    service.generate(db_with_snapshot, repo_id)

    listing = client.get(f"/api/reports?repo_id={repo_id}").json()
    assert listing["total"] == 1
    # 调度配置要如实暴露,免得让人以为周报是凭空冒出来的
    assert listing["scheduler"]["enabled"] is True
    assert listing["scheduler"]["current_period"] == service.current_period_key()

    report_id = listing["items"][0]["id"]
    detail = client.get(f"/api/reports/{report_id}").json()
    assert "## 概况" in detail["body"]


def test_周报接口_手动生成是幂等的(client, db_with_snapshot, repo_id):
    first = client.post(f"/api/reports/generate?repo_id={repo_id}").json()
    second = client.post(f"/api/reports/generate?repo_id={repo_id}").json()
    assert first["id"] == second["id"]


def test_周报接口_不存在的返回_404(client):
    assert client.get("/api/reports/999999").status_code == 404