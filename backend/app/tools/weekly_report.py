"""自动周报与沉淀。

对应原文亮点 7:根据一周的研发活动生成周报,并**回写入知识库**,
让团队的历史产出变成可检索的资产。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import models as m
from app.github.conclusions import is_failed_conclusion
from app.db.seed import SNAPSHOT_DIR
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def weekly_report(ctx: ToolContext, days: int = 7, **_: object) -> ToolResult:
    db, repo_id = ctx.db, ctx.repo_id
    repo = db.get(m.Repo, repo_id)
    since = datetime.now(UTC) - timedelta(days=int(days))

    issues = db.scalars(select(m.Issue).where(m.Issue.repo_id == repo_id)).all()
    prs = db.scalars(select(m.PullRequest).where(m.PullRequest.repo_id == repo_id)).all()
    ci = db.scalars(select(m.CiRun).where(m.CiRun.repo_id == repo_id)).all()

    open_issues = [i for i in issues if i.state == "open"]
    merged = [p for p in prs if p.merged]
    failing = [c for c in ci if is_failed_conclusion(c.conclusion)]

    lines = [
        f"# 研发周报({since:%Y-%m-%d} ~ {datetime.now(UTC):%Y-%m-%d})",
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

    body = "\n".join(lines) + "\n"

    # 回写知识库:落成文档 + 写文件,下次索引即可被检索到
    path = f"docs/weekly-{datetime.now(UTC):%Y%m%d}.md"
    existing = db.scalar(
        select(m.Document).where(m.Document.repo_id == repo_id, m.Document.path == path)
    )
    if existing is None:
        db.add(m.Document(repo_id=repo_id, path=path, title="研发周报",
                          doc_type="markdown", version="auto"))
        db.commit()

    docs_dir = SNAPSHOT_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / path.split("/")[-1]).write_text(body, encoding="utf-8")

    return ToolResult(
        tool="weekly_report",
        summary=f"已生成周报并回写知识库({path}):未处理 Issue {len(open_issues)} 条、"
                f"失败 CI {len(failing)} 次。",
        data={"path": path, "open_issues": len(open_issues), "failed_ci": len(failing),
              "merged_prs": len(merged)},
        evidence_refs=[path],
    )


register(ToolSpec(
    name="weekly_report",
    description="根据最近一周的 Issue、PR、CI 活动生成研发周报,并回写进知识库。",
    parameters={
        "type": "object",
        "properties": {"days": {"type": "integer", "description": "统计天数,默认 7"}},
        "required": [],
    },
    handler=weekly_report,
))