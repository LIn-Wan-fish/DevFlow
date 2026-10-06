from sqlalchemy import func, select

from app.db import models as m
from app.github.conclusions import healthy_filter
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def repo_health(ctx: ToolContext, **_: object) -> ToolResult:
    """仓库健康全景:前端总览六卡片与 img_01 统计条的数据源。"""
    db, repo_id = ctx.db, ctx.repo_id

    open_issues = db.scalar(
        select(func.count()).select_from(m.Issue).where(
            m.Issue.repo_id == repo_id, m.Issue.state == "open")
    ) or 0
    prs_pending = db.scalar(
        select(func.count()).select_from(m.PullRequest).where(
            m.PullRequest.repo_id == repo_id,
            m.PullRequest.state == "open",
            m.PullRequest.merged.is_(False),
        )
    ) or 0
    issues_resolved = db.scalar(
        select(func.count()).select_from(m.Issue).where(
            m.Issue.repo_id == repo_id, m.Issue.group == "handled")
    ) or 0
    issues_rejected = db.scalar(
        select(func.count()).select_from(m.Issue).where(
            m.Issue.repo_id == repo_id, m.Issue.group == "rejected")
    ) or 0
    failed_ci = db.scalar(
        select(func.count()).select_from(m.CiRun).where(
            m.CiRun.repo_id == repo_id, healthy_filter(m.CiRun.conclusion))
    ) or 0
    merged_prs = db.scalar(
        select(func.count()).select_from(m.PullRequest).where(
            m.PullRequest.repo_id == repo_id, m.PullRequest.merged.is_(True))
    ) or 0

    repo = db.get(m.Repo, repo_id)
    data = {
        "repo": repo.full_name if repo else "",
        "open_issues": open_issues,
        "prs_pending_review": prs_pending,
        "issues_resolved": issues_resolved,
        "issues_rejected": issues_rejected,
        "failed_ci": failed_ci,
        "merged_prs": merged_prs,
    }
    summary = (
        f"{data['repo']}:待处理 Issue {open_issues}、待 Review PR {prs_pending}、"
        f"失败 CI {failed_ci}、已合并 PR {merged_prs}。"
    )
    return ToolResult(tool="repo_health", summary=summary, data=data)


register(ToolSpec(
    name="repo_health",
    description="获取当前仓库的健康全景:待处理 Issue、待 Review PR、失败 CI、已合并 PR 等六项统计。",
    parameters={"type": "object", "properties": {}, "required": []},
    handler=repo_health,
))