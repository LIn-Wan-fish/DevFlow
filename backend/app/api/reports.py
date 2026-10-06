"""周报的查看与手动生成。

自动生成由 app/reports/scheduler.py 负责;这里只做「看」和「现在就要一份」。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as m
from app.db.session import get_db
from app.reports import service

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _to_out(r: m.WeeklyReport) -> dict:
    return {
        "id": r.id, "repo_id": r.repo_id, "period_key": r.period_key,
        "period_start": r.period_start.isoformat() if r.period_start else None,
        "period_end": r.period_end.isoformat() if r.period_end else None,
        "trigger": r.trigger, "path": r.path, "summary": r.summary,
        "open_issues": r.open_issues, "merged_prs": r.merged_prs,
        "failed_ci": r.failed_ci,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
    }


@router.get("")
def list_reports(repo_id: int | None = None, limit: int = 20,
                 db: Session = Depends(get_db)) -> dict:
    query = select(m.WeeklyReport)
    if repo_id is not None:
        query = query.where(m.WeeklyReport.repo_id == repo_id)
    rows = db.scalars(query.order_by(m.WeeklyReport.id.desc()).limit(limit)).all()
    return {
        "total": len(rows),
        "items": [_to_out(r) for r in rows],
        # 如实暴露调度配置,免得让人以为周报是"魔法"生成的
        "scheduler": {
            "enabled": settings.weekly_report_enabled,
            "check_seconds": settings.weekly_report_check_seconds,
            "days": settings.weekly_report_days,
            "current_period": service.current_period_key(),
        },
    }


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    report = db.get(m.WeeklyReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"周报 {report_id} 不存在")
    return {**_to_out(report), "body": report.body}


@router.post("/generate")
def generate_now(repo_id: int = 1, db: Session = Depends(get_db)) -> dict:
    """手动生成一份(幂等:本周期已有就直接返回那一份)。"""
    report = service.generate(db, repo_id, days=settings.weekly_report_days,
                              trigger=m.ReportTrigger.MANUAL.value)
    return {**_to_out(report), "body": report.body}