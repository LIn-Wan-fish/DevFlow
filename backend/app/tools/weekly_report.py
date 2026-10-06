"""周报工具:按需生成一份,并回写知识库。

**统计逻辑不在这里** —— 它和自动调度器共用 `app.reports.service`,
避免同一套口径在两处各写一遍(这个项目吃过这个亏:CI 失败判定曾在 6 处重复)。
"""

from __future__ import annotations

from app.config import settings
from app.reports import service
from app.tools.registry import ToolContext, ToolResult, ToolSpec, register


async def weekly_report(ctx: ToolContext, days: int = 0, **_: object) -> ToolResult:
    window = int(days) or settings.weekly_report_days
    report = service.generate(ctx.db, ctx.repo_id, days=window,
                              trigger="manual" if ctx.emit is None else "manual")
    return ToolResult(
        tool="weekly_report",
        summary=f"已生成周报并回写知识库({report.path}):未处理 Issue {report.open_issues} 条、"
                f"已合并 PR {report.merged_prs} 条、失败 CI {report.failed_ci} 次。",
        data={"report_id": report.id, "period_key": report.period_key, "path": report.path,
              "open_issues": report.open_issues, "merged_prs": report.merged_prs,
              "failed_ci": report.failed_ci},
        evidence_refs=[report.path],
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