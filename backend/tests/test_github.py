"""GitHub 适配器的离线测试。

用 httpx.MockTransport 造出一个假的 GitHub,所以这些用例
**不需要 token、不打网络**,却覆盖了真正容易出错的地方:
分页、限流退避、错误映射、ETag/304、日志 ZIP 解压,以及 sync 落库。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from app.db import models as m
from app.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFound,
    GitHubNotConfigured,
    GitHubRateLimited,
    extract_log_text,
)
from app.github.provider import sync_repo

BASE = "https://api.github.com"


def _client(handler, token="tok", **kwargs) -> GitHubClient:
    return GitHubClient(token, BASE, transport=httpx.MockTransport(handler), **kwargs)


# --------------------------------------------------------------------------- 基础


def test_缺_token_直接报错而不是静默():
    with pytest.raises(GitHubNotConfigured):
        GitHubClient(None, BASE)


def test_parse_link_取_next():
    header = ('<https://api.github.com/x?page=2>; rel="next", '
              '<https://api.github.com/x?page=5>; rel="last"')
    assert GitHubClient.parse_link(header) == "https://api.github.com/x?page=2"
    assert GitHubClient.parse_link(None) is None
    assert GitHubClient.parse_link('<https://a>; rel="last"') is None


def test_extract_log_text_解压_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CI/1_build.txt", "build ok")
        archive.writestr("CI/2_test.txt", "E  AssertionError: expected 200 got 401")
    text = extract_log_text(buffer.getvalue())
    assert "2_test.txt" in text
    assert "expected 200 got 401" in text


def test_extract_log_text_纯文本退化成解码():
    assert extract_log_text("plain log".encode()) == "plain log"


# --------------------------------------------------------------------------- 分页 / 错误


async def test_分页会跟着_Link_聚合(monkeypatch):
    pages = {
        "page=1": [{"number": 1}],
        "page=2": [{"number": 2}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            body, link = pages["page=2"], None
        elif "page" not in request.url.params:
            body = pages["page=1"]
            link = f'<{BASE}/items?page=2>; rel="next"'
        else:
            body, link = [], None
        headers = {"Link": link} if link else {}
        return httpx.Response(200, json=body, headers=headers)

    items = await _client(handler)._paginate("/items")
    await _client(handler)._client.aclose()
    assert [i["number"] for i in items] == [1, 2]


async def test_401_映射成认证错误():
    async def scenario():
        client = _client(lambda r: httpx.Response(401, json={}))
        try:
            await client._get("/x")
        finally:
            await client.aclose()

    with pytest.raises(GitHubAuthError):
        await scenario()


async def test_404_映射成资源不存在():
    async def scenario():
        client = _client(lambda r: httpx.Response(404, json={}))
        try:
            await client._get("/x")
        finally:
            await client.aclose()

    with pytest.raises(GitHubNotFound):
        await scenario()


async def test_429_按_RetryAfter_退避后重试成功():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    try:
        body, _ = await client._get("/x")
    finally:
        await client.aclose()
    assert body == {"ok": True}
    assert calls["n"] == 2


async def test_限流等待超过上限时直接报错而不是干等():
    def handler(request: httpx.Request) -> httpx.Response:
        # reset 时间设得很远 → 等待超过 max_backoff,应当立刻报错
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0",
                                            "X-RateLimit-Reset": "9999999999"})

    client = _client(handler, max_backoff_seconds=0.1)
    try:
        with pytest.raises(GitHubRateLimited):
            await client._get("/x")
    finally:
        await client.aclose()


async def test_5xx_重试后仍失败则报错():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    client = _client(handler, max_retries=2)
    try:
        with pytest.raises(GitHubError):
            await client._get("/x")
    finally:
        await client.aclose()
    assert calls["n"] == 3, "应当重试到上限才放弃"


async def test_304_返回缓存体而不是空结果():
    """原实现把 304 当空结果,内容没变时反而拿到空列表 —— 这是错的。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=[{"number": 1}], headers={"ETag": 'W/"v1"'})
        assert request.headers.get("If-None-Match") == 'W/"v1"', "第二次应带 If-None-Match"
        return httpx.Response(304)

    client = _client(handler)
    try:
        first, _ = await client._get("/items")
        second, _ = await client._get("/items")
    finally:
        await client.aclose()
    assert first == [{"number": 1}]
    assert second == [{"number": 1}], "304 必须返回缓存内容"


# --------------------------------------------------------------------------- workflow_log


async def test_workflow_log_跟随重定向并解压():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("1_test.txt", "E   AssertionError: expected 200 got 401")
    payload = buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "logs.example":
            return httpx.Response(200, content=payload,
                                  headers={"Content-Type": "application/zip"})
        return httpx.Response(302, headers={"Location": "https://logs.example/blob"})

    client = _client(handler)
    try:
        text = await client.workflow_log("acme", "clowder-ai", 512)
    finally:
        await client.aclose()
    assert "expected 200 got 401" in text


# --------------------------------------------------------------------------- sync_repo


def _sync_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/repos/acme/clowder-ai":
        return httpx.Response(200, json={
            "name": "clowder-ai", "owner": {"login": "acme"},
            "default_branch": "master", "description": "项目展示页",
        })
    if path.endswith("/issues"):
        return httpx.Response(200, json=[
            {"number": 24, "title": "登录报错", "body": "线上 401", "state": "open",
             "labels": [{"name": "bug"}, {"name": "priority:P0"}],
             "user": {"login": "zhangsan"}, "assignee": None},
            # issues 接口也会返回 PR,必须被过滤掉
            {"number": 12, "title": "修复登录", "pull_request": {"url": "x"}},
        ])
    if path.endswith("/pulls"):
        # 必须带 state=all,否则已合并的 PR 进不来,总览的 merged_prs 永远是 0
        assert request.url.params.get("state") == "all", "同步必须拉全部状态的 PR"
        return httpx.Response(200, json=[
            {"number": 12, "title": "修复登录 401", "body": "", "state": "open",
             "head": {"ref": "fix-login"}, "base": {"ref": "main"},
             "additions": 128, "deletions": 43, "changed_files": 2,
             "merged_at": None, "user": {"login": "wangwu"}},
            {"number": 11, "title": "已合并的改动", "body": "", "state": "closed",
             "head": {"ref": "old"}, "base": {"ref": "main"},
             "additions": 5, "deletions": 1, "changed_files": 1,
             "merged_at": "2026-10-06T00:00:00Z", "user": {"login": "zhangsan"}},
        ])
    if "/pulls/" in path and path.endswith("/files"):
        number = path.split("/pulls/")[1].split("/")[0]
        if number == "12":
            return httpx.Response(200, json=[
                {"filename": "src/auth/login.py", "additions": 42, "deletions": 18, "patch": "@@"},
                {"filename": "docs/api.md", "additions": 3, "deletions": 1, "patch": "@@"},
            ])
        return httpx.Response(200, json=[
            {"filename": "README.md", "additions": 5, "deletions": 1, "patch": "@@"},
        ])
    if path.endswith("/actions/runs"):
        return httpx.Response(200, json={"workflow_runs": [
            {"id": 512, "name": "CI", "head_branch": "fix-login", "status": "completed",
             "conclusion": "failure", "head_sha": "abc", "display_title": "fix(auth)"},
            {"id": 511, "name": "CI", "head_branch": "main", "status": "completed",
             "conclusion": "success", "head_sha": "def", "display_title": "chore"},
            # startup_failure 是真实存在的结论(用户仓库里 6 次全是它),
            # 同样需要日志 —— 判据不能写成 `== "failure"`
            {"id": 510, "name": "Pages", "head_branch": "master", "status": "completed",
             "conclusion": "startup_failure", "head_sha": "ghi", "display_title": "pages"},
        ]})
    if path.endswith("/actions/runs/512/logs") or path.endswith("/actions/runs/510/logs"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("1_test.txt", "E   AssertionError: expected 200 got 401")
        return httpx.Response(302, headers={"Location": "https://logs.example/blob"})
    if request.url.host == "logs.example":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("1_test.txt", "E   AssertionError: expected 200 got 401")
        return httpx.Response(200, content=buffer.getvalue())
    raise AssertionError(f"未预期的请求: {request.url}")


async def test_sync_repo_落库_过滤_pr_标记高风险_并拉取失败_ci_日志(
    db, monkeypatch, tmp_path
):
    repo = m.Repo(owner="acme", name="clowder-ai", is_github=True)
    db.add(repo)
    db.commit()

    client = _client(_sync_handler)
    monkeypatch.setattr("app.github.provider.require_client", lambda: client)
    monkeypatch.setattr("app.github.provider.SNAPSHOT_DIR", tmp_path)

    counts = await sync_repo(db, repo.id)

    # issues 接口返回的两条里,PR 那条必须被过滤
    assert counts["issues"] == 1
    assert db.query(m.Issue).filter_by(number=12).count() == 0
    assert db.query(m.Issue).filter_by(number=24).one().labels == ["bug", "priority:P0"]

    assert counts["pulls"] == 2, "开放的与已合并的都要进库"
    files = db.query(m.PrFile).all()
    assert any(f.is_high_risk for f in files if "auth" in f.path)
    assert not any(f.is_high_risk for f in files if f.path == "docs/api.md")

    assert counts["ci_runs"] == 3
    assert counts["ci_logs"] == 2, "failure 与 startup_failure 都要拉日志;success 不拉"

    failed = db.query(m.CiRun).filter_by(number=512).one()
    assert failed.log_path and Path(failed.log_path).exists()
    assert "expected 200 got 401" in Path(failed.log_path).read_text(encoding="utf-8")

    passed = db.query(m.CiRun).filter_by(number=511).one()
    assert passed.log_path == "", "成功的 CI 不需要拉日志"


async def test_sync_repo_日志拉取失败不阻断同步(db, monkeypatch, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/actions/runs/512/logs", "/actions/runs/510/logs")):
            return httpx.Response(404)
        return _sync_handler(request)

    repo = m.Repo(owner="acme", name="clowder-ai", is_github=True)
    db.add(repo)
    db.commit()

    client = _client(handler)
    monkeypatch.setattr("app.github.provider.require_client", lambda: client)
    monkeypatch.setattr("app.github.provider.SNAPSHOT_DIR", tmp_path)

    counts = await sync_repo(db, repo.id)
    assert counts["ci_runs"] == 3, "日志拿不到不应影响 Issue/PR/CI 的落库"
    assert counts["ci_logs"] == 0
    assert db.query(m.CiRun).filter_by(number=512).one().log_path == ""


async def test_sync_repo_幂等(db, monkeypatch, tmp_path):
    repo = m.Repo(owner="acme", name="clowder-ai", is_github=True)
    db.add(repo)
    db.commit()
    monkeypatch.setattr("app.github.provider.require_client",
                        lambda: _client(_sync_handler))
    monkeypatch.setattr("app.github.provider.SNAPSHOT_DIR", tmp_path)

    first = await sync_repo(db, repo.id)
    second = await sync_repo(db, repo.id)

    assert first["issues"] == 1 and second["issues"] == 0
    assert first["ci_runs"] == 3 and second["ci_runs"] == 0
    assert db.query(m.Issue).count() == 1