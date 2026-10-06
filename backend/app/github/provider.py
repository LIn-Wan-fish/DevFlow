"""数据源适配:snapshot(默认)与 github 两种实现,同一套接口。

刻意不做「GitHub 不通就静默回退快照」:那会让人把假数据当成真实结论。
token 没配就明确报错。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

import logging
from pathlib import Path

from app.config import settings
from app.db import models as m
from app.db.seed import SNAPSHOT_DIR
from app.github.client import GitHubClient, GitHubError, GitHubNotConfigured
from app.github.conclusions import HEALTHY_CONCLUSIONS
from app.safety.policy import is_high_risk_path

logger = logging.getLogger(__name__)

# 这些结论不需要日志(成功/跳过/中性),与 conclusions.HEALTHY_CONCLUSIONS 同一份名单
LOG_FETCH_SKIP = HEALTHY_CONCLUSIONS


def require_client() -> GitHubClient:
    if settings.data_source != "github":
        raise RuntimeError("当前 DATA_SOURCE 不是 github")
    return GitHubClient(settings.github_token, settings.github_api_base)


def _write_log(repo_id: int, run_id: int, text: str) -> "Path":
    """把 CI 日志落到本地文件。

    落文件而不是塞数据库:日志可能很大,而且 CIDebugAgent 是按路径读的。
    """
    directory = SNAPSHOT_DIR / "ci_logs_github"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"repo{repo_id}-run{run_id}.log"
    path.write_text(text, encoding="utf-8")
    return path


def _target_number(target: str) -> int:
    digits = "".join(ch for ch in target if ch.isdigit())
    if not digits:
        raise ValueError(f"无法从 {target!r} 解析出编号")
    return int(digits)


def execute_write_action(db: Session, draft: m.ActionDraft) -> None:
    """真实写操作。只有经过人工确认的草稿才会走到这里。"""
    repo = db.get(m.Repo, draft.repo_id)
    if repo is None:
        raise LookupError("仓库不存在")
    number = _target_number(draft.target)

    async def run() -> None:
        client = require_client()
        try:
            if draft.action == "comment_on_issue":
                await client.create_issue_comment(repo.owner, repo.name, number,
                                                  str(draft.payload.get("body", "")))
            elif draft.action == "add_labels":
                await client.add_labels(repo.owner, repo.name, number,
                                        list(draft.payload.get("labels", [])))
            elif draft.action == "close_issue":
                await client.update_issue(repo.owner, repo.name, number, state="closed")
            elif draft.action == "reopen_issue":
                await client.update_issue(repo.owner, repo.name, number, state="open")
            else:
                raise ValueError(f"未支持的写操作 {draft.action}")
        finally:
            await client.aclose()

    asyncio.run(run())


async def sync_repo(db: Session, repo_id: int, *, limit: int = 100,
                    fetch_logs: bool = True) -> dict[str, int]:
    """把 GitHub 上的 Issue / PR / CI 同步进本地库。

    本地库始终是「当前视图」,Agent 读本地库即可 ——
    否则每次工具调用都要打网络,又慢又容易触发限流。
    """
    repo = db.get(m.Repo, repo_id)
    if repo is None:
        raise LookupError("仓库不存在")

    client = require_client()
    counts = {"issues": 0, "pulls": 0, "ci_runs": 0, "ci_logs": 0}
    try:
        for raw in await client.list_issues(repo.owner, repo.name):
            if "pull_request" in raw:  # GitHub 的 issues 接口会把 PR 也返回
                continue
            exists = db.query(m.Issue).filter_by(
                repo_id=repo_id, number=raw["number"]).one_or_none()
            if exists:
                continue
            db.add(m.Issue(
                repo_id=repo_id,
                number=raw["number"],
                title=raw.get("title", ""),
                body=raw.get("body") or "",
                state=raw.get("state", "open"),
                labels=[lbl["name"] for lbl in raw.get("labels", [])],
                author=(raw.get("user") or {}).get("login", ""),
                assignee=((raw.get("assignee") or {}) or {}).get("login"),
                group="unarchived",
            ))
            counts["issues"] += 1

        # state="all":默认的 "open" 只抓开放 PR,那样总览里的 `merged_prs`
        # 在真实数据上会**永远是 0**(已合并的 PR 根本没进库)。
        # 评审视图仍然只看开放的,但统计与历史需要全量。
        for raw in await client.list_pulls(repo.owner, repo.name, state="all"):
            exists = db.query(m.PullRequest).filter_by(
                repo_id=repo_id, number=raw["number"]).one_or_none()
            if exists:
                continue
            pr = m.PullRequest(
                repo_id=repo_id,
                number=raw["number"],
                title=raw.get("title", ""),
                body=raw.get("body") or "",
                state=raw.get("state", "open"),
                head_ref=(raw.get("head") or {}).get("ref", ""),
                base_ref=(raw.get("base") or {}).get("ref", "main"),
                additions=raw.get("additions", 0),
                deletions=raw.get("deletions", 0),
                changed_files=raw.get("changed_files", 0),
                merged=bool(raw.get("merged_at")),
                author=(raw.get("user") or {}).get("login", ""),
            )
            db.add(pr)
            db.flush()
            for f in await client.pull_files(repo.owner, repo.name, raw["number"]):
                db.add(m.PrFile(
                    pr_id=pr.id,
                    path=f.get("filename", ""),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                    patch_summary=(f.get("patch") or "")[:500],
                    is_high_risk=is_high_risk_path(f.get("filename", "")),
                ))
            counts["pulls"] += 1

        for raw in await client.list_workflow_runs(repo.owner, repo.name):
            run_id = raw["id"]
            row = db.query(m.CiRun).filter_by(repo_id=repo_id, number=run_id).one_or_none()
            if row is None:
                row = m.CiRun(
                    repo_id=repo_id,
                    number=run_id,
                    workflow=(raw.get("name") or "CI"),
                    branch=raw.get("head_branch") or "",
                    status=raw.get("status", "completed"),
                    conclusion=raw.get("conclusion") or "unknown",
                    commit_sha=raw.get("head_sha", ""),
                    commit_message=raw.get("display_title", ""),
                    log_path="",
                    duration_seconds=0,
                )
                db.add(row)
                counts["ci_runs"] += 1
            db.flush()

            # 非成功的运行都要拉日志,否则 CI 排障只会回「未找到日志」。
            #
            # 注意判据是「不在成功集合里」,而不是 `== "failure"`:
            # GitHub 的结论还有 startup_failure / timed_out / cancelled / action_required。
            # 这条是被真实数据打出来的 —— 用户仓库里 6 次运行全是 startup_failure,
            # 按 `== "failure"` 判断的话一个日志都不会去拉。
            if fetch_logs and row.conclusion not in LOG_FETCH_SKIP and not row.log_path:
                try:
                    text = await client.workflow_log(repo.owner, repo.name, run_id)
                except GitHubError as exc:
                    logger.warning("拉取 CI #%s 日志失败,该次排障将缺少证据:%s", run_id, exc)
                else:
                    row.log_path = str(_write_log(repo_id, run_id, text))
                    counts["ci_logs"] += 1

        # 用真实元数据回填。之前只设 is_github,default_branch 一直是模型默认值 "main",
        # 而用户仓库的实际默认分支是 "master" —— 同步来的数据带着错的分支信息。
        try:
            meta = await client.get_repo(repo.owner, repo.name)
        except GitHubError as exc:
            logger.warning("拉取仓库元数据失败,沿用已有字段:%s", exc)
        else:
            repo.owner = (meta.get("owner") or {}).get("login") or repo.owner
            repo.name = meta.get("name") or repo.name
            repo.default_branch = meta.get("default_branch") or repo.default_branch
            if meta.get("description"):
                repo.description = meta["description"]

        repo.is_github = True
        db.commit()
    finally:
        await client.aclose()
    return counts


__all__ = ["GitHubNotConfigured", "execute_write_action", "require_client", "sync_repo"]