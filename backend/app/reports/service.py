"""自动周报:生成、回写知识库、幂等。

**为什么要有服务层**:周报原先只有一个 `weekly_report` 工具(按需调用)。
「自动」意味着还要有调度、落库、可浏览 —— 如果每个入口各写一份统计逻辑,
口径迟早漂移。这个项目已经吃过一次亏:CI 失败判定曾经在 6 个地方各写了一遍
`conclusion == "failure"`,漏掉了 `startup_failure`。所以这里只保留**一份**实现,
工具、调度器、API 全部调它。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.seed import SNAPSHOT_DIR
from app.github.conclusions import is_failed_conclusion

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 7


def current_period_key(now: datetime | None = None) -> str:
    """周期标识,例如 `2026-W41`。

    用 ISO 周做幂等键:同一周无论调度器检查多少次,只会有一份周报。
    """
    moment = now or datetime.now(UTC)
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def build_body(db: Session, repo_id: int, *, days: int = DEFAULT_DAYS,
               now: datetime | None = None) -> tuple[str, dict, datetime, datetime]:
    """生成周报正文与统计。返回 (正文, 统计, 周期起, 周期止)。"""
    moment = now or datetime.now(UTC)
    since = moment - timedelta(days=int(days))
    repo = db.get(m.Repo, repo_id)

    issues = db.scalars(select(m.Issue).where(m.Issue.repo_id == repo_id)).all()
    prs = db.scalars(select(m.PullRequest).where(m.PullRequest.repo_id == repo_id)).all()
    ci = db.scalars(select(m.CiRun).where(m.CiRun.repo_id == repo_id)).all()

    open_issues = [i for i in issues if i.state == "open"]
    merged = [p for p in prs if p.merged]
    failing = [c for c in ci if is_failed_conclusion(c.conclusion)]

    lines = [
        f"# 研发周报({since:%Y-%m-%d} ~ {moment:%Y-%m-%d})",
        "",
        f"仓库:{repo.full_name if repo else repo_id}",
        "",
        "## 概况",
        "",
        f"- 未处理 Issue:{len(open_issues)} 条",
        f"- 已合并 PR:{len(merged)} 条",
        f"- 失败 CI:{len(failing)} 次",
        "",
        "## 待跟进",
        "",
    ]
    for issue in open_issues:
        lines.append(f"- Issue #{issue.number} {issue.title}({issue.state})")
    for run in failing:
        lines.append(f"- CI #{run.number} 在 {run.branch} 分支失败")
    lines += ["", "## 风险提示", ""]
    if failing and merged:
        lines.append("- 存在失败 CI 的同时已有 PR 合入,需要确认失败流水线是否影响已合并的改动。")
    else:
        lines.append("- 暂无阻塞性风险。")

    stats = {"open_issues": len(open_issues), "merged_prs": len(merged),
             "failed_ci": len(failing)}
    return "\n".join(lines) + "\n", stats, since, moment


def _write_back(db: Session, repo_id: int, path: str, body: str) -> None:
    """回写知识库:落 Document 记录 + 写文件,下一轮索引即可被检索到。"""
    existing = db.scalar(
        select(m.Document).where(m.Document.repo_id == repo_id, m.Document.path == path)
    )
    if existing is None:
        db.add(m.Document(repo_id=repo_id, path=path, title="研发周报",
                          doc_type="markdown", version="auto"))

    docs_dir = SNAPSHOT_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / path.split("/")[-1]).write_text(body, encoding="utf-8")


def generate(db: Session, repo_id: int, *, days: int = DEFAULT_DAYS,
             trigger: str = "manual", now: datetime | None = None) -> m.WeeklyReport:
    """生成(或取回)本周期周报。**幂等**:同一周期只会有一份。"""
    key = current_period_key(now)
    existing = db.scalar(
        select(m.WeeklyReport).where(
            m.WeeklyReport.repo_id == repo_id, m.WeeklyReport.period_key == key
        )
    )
    if existing is not None:
        return existing

    body, stats, since, until = build_body(db, repo_id, days=days, now=now)
    path = f"docs/weekly-{until:%Y%m%d}.md"
    _write_back(db, repo_id, path, body)

    report = m.WeeklyReport(
        repo_id=repo_id, period_key=key, period_start=since, period_end=until,
        trigger=trigger, path=path, body=body,
        summary=f"未处理 Issue {stats['open_issues']} 条、已合并 PR {stats['merged_prs']} 条、"
                f"失败 CI {stats['failed_ci']} 次",
        **stats,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def is_due(db: Session, repo_id: int, now: datetime | None = None) -> bool:
    """本周期是否还缺一份周报。"""
    key = current_period_key(now)
    found = db.scalar(
        select(m.WeeklyReport.id).where(
            m.WeeklyReport.repo_id == repo_id, m.WeeklyReport.period_key == key
        )
    )
    return found is None