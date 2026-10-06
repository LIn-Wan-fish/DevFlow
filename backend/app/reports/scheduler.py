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
from app.core.cache import get_cache
from app.db import models as m
from app.db.session import SessionLocal
from app.reports import service

logger = logging.getLogger(__name__)


def check_once(session_factory=SessionLocal) -> int:
    """检查所有仓库,给缺周报的补一份。返回本次生成的数量。

    `session_factory` 可注入:默认用真实数据库,单测里传一个产出测试会话的工厂,
    这样调度逻辑本身也能被单测覆盖(它原先直接绑死 SessionLocal,测不到一起)。
    """
    generated = 0
    try:
        with session_factory() as db:
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


LOCK_NAME = "weekly-report-check"


async def run(stop: asyncio.Event) -> None:
    """周期检查。启动时先跑一次,然后按间隔轮询。

    **多副本下只有一个副本会真正执行**:检查前先抢一把带过期时间的锁。
    锁保证的是「同一时刻只有一个副本在跑」;而 `(repo_id, period_key)` 唯一约束
    保证的是「同一周期不会写两份」。两者叠加才既省模型调用、又不出重复数据。

    少了锁会怎样:两个副本同时判定「该出周报了」,于是**两边都调一遍模型**,
    最后靠唯一约束挡住其中一个 —— 数据是对的,但钱白花了。
    """
    cache = get_cache()
    while not stop.is_set():
        try:
            # 锁的过期时间取检查间隔:持锁进程被 kill 时锁能自己过期,
            # 否则调度会永久停摆 —— 那比重复执行更糟。
            ttl = max(60, settings.weekly_report_check_seconds)
            if await cache.acquire_lock(LOCK_NAME, ttl):
                try:
                    await asyncio.to_thread(check_once)
                finally:
                    # 只做一次检查就放锁,让下一个周期的副本有机会接手
                    await cache.release_lock(LOCK_NAME)
            else:
                logger.debug("另一个副本正在检查周报,本轮跳过")
        except Exception:  # noqa: BLE001
            # **循环体里任何异常都不能逃出去**。一旦逃出去这个 while 就结束了,
            # 之后再也不会检查周报 —— 而且是静默的:没有报错、没有告警,
            # 只是周报不再生成。check_once 内部已经兜了一层,这里是第二层,
            # 防的是"以后有人改动时不小心引入异常"。
            logger.exception("周报调度本轮失败,下一轮重试")

        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.weekly_report_check_seconds)
        except TimeoutError:
            continue
    logger.info("自动周报调度器已停止")