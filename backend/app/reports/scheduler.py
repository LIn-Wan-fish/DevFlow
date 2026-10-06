"""自动周报的调度器。

**这是一个进程内 asyncio 循环,不是生产级调度器。** 单容器 Demo 够用,
但边界必须写清楚,免得被当成能上生产的东西:

- 多副本部署时每个副本都会触发。`weekly_reports` 上的 (repo_id, period_key)
  唯一约束保证**不会重复写**,但会白跑几次。
- 进程重启会重置计时。所以启动时先检查一次 —— 保证「漏了」比「重了」更不可能发生。
- 生产环境应该换成 Celery beat / cron / 平台定时任务,把生成逻辑原样搬过去即可
  (这份循环里除调度外的部分都在 service.py,可复用)。

同步的数据库操作丢进线程池执行,不阻塞事件循环 —— 否则周报检查会卡住正在进行的对话流。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.db import models as m
from app.db.session import SessionLocal
from app.reports import service

logger = logging.getLogger(__name__)


def check_once() -> int:
    """检查所有仓库,给缺周报的补一份。返回本次生成的数量。"""
    generated = 0
    try:
        with SessionLocal() as db:
            for repo in db.scalars(select(m.Repo)).all():
                if not service.is_due(db, repo.id):
                    continue
                report = service.generate(
                    db, repo.id, days=settings.weekly_report_days, trigger="auto"
                )
                logger.info("自动生成周报:%s → %s(%s)", repo.full_name, report.path,
                            report.period_key)
                generated += 1
    except Exception:  # noqa: BLE001
        # 调度器自己绝不能挂:一次失败下一轮重试,不带崩整个应用
        logger.exception("自动周报检查失败,下一轮重试")
    return generated


async def run(stop: asyncio.Event) -> None:
    """周期检查。启动时先跑一次,然后按间隔轮询。"""
    while not stop.is_set():
        await asyncio.to_thread(check_once)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.weekly_report_check_seconds)
        except TimeoutError:
            continue
    logger.info("自动周报调度器已停止")