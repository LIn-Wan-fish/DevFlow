"""仓库的添加与同步。

**为什么抽出来**:这套逻辑原先只写在 `main.py` 的启动流程里,
「添加项目」要用就得再抄一份 —— 这个项目已经吃过一次亏
(CI 失败判定曾在 6 个地方各写一遍,漏掉 startup_failure)。所以只留一份实现。

设计上按**每个仓库独立**处理:内置快照仓库与后来添加的 GitHub 仓库是并列的项目,
各自的数据来源写在 `is_github` 上。这样不会出现「同一个仓库一半快照一半真实」的混用。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.github.client import (
    GitHubAuthError,
    GitHubError,
    GitHubNotFound,
    GitHubNotConfigured,
    GitHubRateLimited,
)
from app.github.provider import require_client, sync_repo

logger = logging.getLogger(__name__)

# owner/name:GitHub 的用户名与仓库名只允许字母数字与 - _ . 这几种符号
FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoAddError(Exception):
    """添加仓库失败。`status` 是可直接回给前端的 HTTP 状态码,`detail` 是给用户看的原因。"""

    def __init__(self, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def parse_full_name(raw: str) -> tuple[str, str]:
    """把 `owner/name` 拆开并做基本校验。也接受直接粘贴整个仓库 URL。"""
    text = (raw or "").strip()
    text = re.sub(r"^https?://(www\.)?github\.com/", "", text, flags=re.IGNORECASE)
    text = text.rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if not FULL_NAME_RE.match(text):
        raise RepoAddError(
            "仓库名要写成 owner/name(例如 LIn-Wan-fish/DevFlow),也可以直接粘贴 GitHub 仓库地址。"
        )
    owner, _, name = text.partition("/")
    return owner.strip(), name.strip()


def find(db: Session, owner: str, name: str) -> m.Repo | None:
    return db.scalar(select(m.Repo).where(m.Repo.owner == owner, m.Repo.name == name))


async def add_repo(db: Session, full_name: str, *, sync: bool = True) -> tuple[m.Repo, dict]:
    """按 `owner/name` 添加仓库并同步数据。**幂等**:已存在则直接返回。

    同步失败时不会留下一具空壳:先确认仓库真的可见,再建行。
    否则界面上会多出一个永远为空的「幽灵项目」,比直接报错更难排查。
    """
    owner, name = parse_full_name(full_name)

    existing = find(db, owner, name)
    if existing is not None:
        return existing, {"already_exists": True}

    try:
        client = require_client(explicit=True)
    except GitHubNotConfigured as exc:
        raise RepoAddError(
            "未配置 GITHUB_TOKEN,无法访问 GitHub 仓库。内置快照仓库不受影响,"
            "但添加新仓库需要真实令牌。",
        ) from exc

    try:
        meta = await client.get_repo(owner, name)
    except GitHubNotFound as exc:
        raise RepoAddError(
            f"仓库 {owner}/{name} 不存在,或者当前令牌看不到它。"
            "私有仓库需要把令牌的 Repository access 加上这个仓库。",
            404,
        ) from exc
    except GitHubAuthError as exc:
        raise RepoAddError(f"GitHub 令牌无效或已过期:{exc}", 401) from exc
    except GitHubRateLimited as exc:
        raise RepoAddError(f"触发 GitHub 速率限制,请稍后再试:{exc}", 429) from exc
    except GitHubError as exc:
        raise RepoAddError(f"访问 GitHub 失败:{exc}", 502) from exc
    except RuntimeError as exc:
        # require_client 在非 github 模式下会抛这个;显式添加时不该走到这里,
        # 但真走到了也要给出可读原因,而不是 500 空响应
        raise RepoAddError(f"无法创建 GitHub 客户端:{exc}", 400) from exc

    repo = m.Repo(
        owner=owner, name=name, is_github=True,
        default_branch=meta.get("default_branch") or "main",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    if not sync:
        return repo, {}

    try:
        counts = await sync_repo(db, repo.id, explicit=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("仓库 %s 已创建但同步失败", repo.full_name)
        raise RepoAddError(
            f"仓库 {repo.full_name} 已创建,但同步数据失败:{exc}。可以稍后重试同步。",
            502,
        ) from exc

    logger.info("已添加仓库 %s,同步结果:%s", repo.full_name, counts)
    return repo, counts


async def resync(db: Session, repo: m.Repo) -> dict:
    """重新同步一个已有仓库。**只对 GitHub 仓库有意义** —— 快照仓库如实拒绝。"""
    if not repo.is_github:
        raise RepoAddError(
            f"{repo.full_name} 是内置快照仓库,没有可同步的上游。"
            "它由 data/snapshot 目录装载。",
        )
    try:
        return await sync_repo(db, repo.id, explicit=True)
    except GitHubNotConfigured as exc:
        raise RepoAddError("未配置 GITHUB_TOKEN,无法同步。") from exc
    except GitHubError as exc:
        raise RepoAddError(f"同步失败:{exc}", 502) from exc