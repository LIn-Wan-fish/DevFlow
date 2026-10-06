"""FastAPI 入口。

lifespan 里做三件事:建表、装载研发数据快照、确保知识库已索引。
Milvus 可能要几十秒才就绪,所以这里是重试而不是直接失败 ——
但失败会明确记日志,不会静默降级成「没有检索能力」。
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

# 必须显式配置日志。uvicorn 只给自己的 logger 装 handler,
# root 是空的 —— 应用自己的 logger 会**静默丢弃**。
# 这一条是实测踩出来的:DATA_SOURCE=github 且没配 token 时,
# 代码里明明 logger.error 了「不装载任何数据」,但容器日志里一个字都没有,
# 于是「明确报错」等于没有报错。
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from app.api import (auth, chat, ci, drafts, issues, mcp as mcp_api, memory, prs, rag,
                     reports, repos, runs, skills)
from app.api import eval as eval_api
from app.config import settings

logger = logging.getLogger(__name__)

MILVUS_WAIT_SECONDS = 90


def _ensure_knowledge_index() -> None:
    from sqlalchemy import func, select

    from app.db import models as m
    from app.db.session import SessionLocal
    from app.rag.indexer import index_repo
    from app.rag.vectorstore import get_vector_store

    deadline = time.time() + MILVUS_WAIT_SECONDS
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            get_vector_store().ensure_collection()
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(3)
    else:
        logger.error("Milvus 在 %ss 内未就绪,跳过索引:%s", MILVUS_WAIT_SECONDS, last_error)
        return

    with SessionLocal() as db:
        repo = db.scalar(select(m.Repo).order_by(m.Repo.id))
        if repo is None:
            logger.warning("没有仓库,跳过索引")
            return
        existing = db.scalar(
            select(func.count()).select_from(m.Chunk).where(m.Chunk.repo_id == repo.id)
        ) or 0
        if existing:
            logger.info("知识库已有 %s 个切分,跳过索引", existing)
            return
        stats = index_repo(db, repo.id)
        logger.info("知识库索引完成:%s", stats)


def _ensure_schema() -> None:
    """建表,并把 alembic 版本对齐。

    本 Demo 允许两条建表路径:
      A) `docker compose up` —— 应用自己 create_all 建表(开箱即用)
      B) `alembic upgrade head` —— 用迁移建表(正规做法)

    两条路径落到同一套 schema。但如果不把 alembic_version 对齐,
    先走 A 再走 B 会因为「表已存在」而直接报错 ——
    这是冷启动最容易踩的坑,所以这里统一收口。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app.db import models as m  # noqa: F401  确保模型注册
    from app.db.base import Base
    from app.db.session import engine

    inspector = inspect(engine)
    if inspector.has_table("alembic_version"):
        # 已经由 alembic 管理,建表交给迁移,不要插手
        return

    Base.metadata.create_all(engine)
    try:
        command.stamp(Config("alembic.ini"), "head")
        logger.info("schema 由应用创建,alembic 版本已对齐到 head")
    except Exception:  # noqa: BLE001
        logger.warning("alembic 版本对齐失败;后续 alembic 命令可能需要手工 stamp",
                       exc_info=True)

async def _ensure_data() -> None:
    """按 DATA_SOURCE 决定装载什么数据。

    **这里修的是一个诚信问题**:原实现无论如何都 `load_snapshot`,
    于是切到 `DATA_SOURCE=github` 后,界面显示的是**快照数据**,
    而 `/api/health` 却报 `data_source=github`。
    那正是 Spec 与 README 里声称「绝不静默回退到快照数据」的行为。

    现在的规则:snapshot 模式装快照;github 模式要么同步真实数据,
    要么**什么都不放**(界面显示空数据)——绝不用假数据顶替。
    """
    from sqlalchemy import select

    from app.db import models as m
    from app.db.seed import load_snapshot
    from app.db.session import SessionLocal
    from app.github.client import GitHubNotConfigured
    from app.github.provider import sync_repo

    if settings.data_source == "snapshot":
        with SessionLocal() as db:
            counts = load_snapshot(db)
        logger.info("研发数据快照装载:%s", counts)
        return

    if not settings.github_token:
        logger.error(
            "DATA_SOURCE=github 但未配置 GITHUB_TOKEN:不装载任何数据。"
            "界面会显示空数据(而不是快照数据);配置 token 后重启即可同步。"
        )
        return
    if not settings.github_repo or "/" not in settings.github_repo:
        logger.error(
            "DATA_SOURCE=github 但未配置 GITHUB_REPO(形如 owner/name):不装载任何数据。"
        )
        return

    owner, _, name = settings.github_repo.partition("/")
    owner, name = owner.strip(), name.strip()
    with SessionLocal() as db:
        repo = db.scalar(select(m.Repo).where(m.Repo.owner == owner, m.Repo.name == name))
        if repo is None:
            repo = m.Repo(owner=owner, name=name, is_github=True)
            db.add(repo)
            db.commit()
        try:
            counts = await sync_repo(db, repo.id)
        except GitHubNotConfigured as exc:
            logger.error("GitHub 同步失败:%s", exc)
            return
        except Exception:  # noqa: BLE001
            logger.exception("GitHub 同步失败;界面将显示空数据")
            return
    logger.info("GitHub 数据同步完成:%s", counts)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001, ARG001
    import asyncio
    import contextlib

    from app.reports import scheduler

    _ensure_schema()
    await _ensure_data()
    _ensure_knowledge_index()

    # 自动周报:启动时先检查一次(保证不漏),之后按间隔轮询。
    # 进程内循环,不是生产级调度 —— 边界写在 app/reports/scheduler.py 顶部。
    stop = asyncio.Event()
    task: asyncio.Task | None = None
    if settings.weekly_report_enabled:
        task = asyncio.create_task(scheduler.run(stop))

    try:
        yield
    finally:
        if task is not None:
            stop.set()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=10)


app = FastAPI(title="DevFlow AI", version="0.1.0", lifespan=lifespan)

for router in (chat.router, repos.router, issues.router, prs.router, ci.router,
               rag.router, drafts.router, memory.router, runs.router, eval_api.router,
               mcp_api.router, skills.router, auth.router, reports.router):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    from app.api.auth import is_enforced

    return {
        "status": "ok",
        "llm_mode": settings.llm_mode,
        "embed_mode": settings.embed_mode,
        "data_source": settings.data_source,
        # 只在真正使用 github 模式时报告,避免 snapshot 模式下让人以为在用真实仓库
        "github_repo": settings.github_repo if settings.data_source == "github" else None,
        # 权限体系是否有认证。false 表示演示模式,前端会如实提示
        "auth_enforced": is_enforced(),
        "version": app.version,
    }