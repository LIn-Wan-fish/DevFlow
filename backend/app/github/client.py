"""GitHub REST 适配器。

只在 DATA_SOURCE=github 时使用。刻意不引入 PyGithub:
需要的就这几个接口,自己写反而能把分页、限流退避、错误映射讲清楚。
"""

from __future__ import annotations

import asyncio
import io
import time
import zipfile
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class GitHubError(Exception):
    """GitHub 调用的领域异常基类。"""


class GitHubNotConfigured(GitHubError):
    def __init__(self) -> None:
        super().__init__(
            "DATA_SOURCE=github 但未配置 GITHUB_TOKEN。"
            "请在 .env 里填入 token —— 本系统不会静默回退到快照数据。"
        )


class GitHubAuthError(GitHubError):
    pass


class GitHubNotFound(GitHubError):
    pass


class GitHubRateLimited(GitHubError):
    pass


# url -> (etag, body)。做成进程级共享:原先挂在实例上,而 provider 每次调用都新建
# client,缓存永远命中不了,等于没有。304 必须返回缓存体 —— 原实现把 304 当空结果,
# 内容没变时反而会拿到空列表,是错的。
_ETAG_CACHE: dict[str, tuple[str, object]] = {}


def extract_log_text(payload: bytes) -> str:
    """GitHub Actions 的日志接口返回的是 **ZIP**,不是纯文本。

    不解压的话,CI 排障只会拿到一堆乱码或直接失败。
    """
    if payload[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                parts: list[str] = []
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    parts.append(f"===== {name} =====")
                    parts.append(archive.read(name).decode("utf-8", errors="replace"))
                return "\n".join(parts)
        except zipfile.BadZipFile:
            pass  # 不是合法 zip,退化成纯文本
    return payload.decode("utf-8", errors="replace")


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        base_url: str = "https://api.github.com",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        if not token:
            raise GitHubNotConfigured()
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._max_backoff = max_backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "devflow-ai-demo",
            },
            timeout=20.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- 基础设施

    @staticmethod
    def parse_link(header: str | None) -> str | None:
        """从 Link 头里取 rel="next"。"""
        if not header:
            return None
        for part in header.split(","):
            segments = part.split(";")
            if len(segments) < 2:
                continue
            url = segments[0].strip().strip("<>")
            if any('rel="next"' in s for s in segments[1:]):
                return url
        return None

    async def _get(self, path: str, params: dict | None = None) -> tuple[Any, httpx.Headers]:
        """返回 (body, headers)。

        headers 必须是 httpx.Headers —— 它是大小写不敏感的。
        曾经这里返回 dict(response.headers),而 dict 会把头名**全部小写**,
        于是 Link / Retry-After / X-RateLimit-* / ETag 一个都读不到:
        分页永远停在第 1 页、限流退避永不生效、ETag 缓存永不命中。
        """
        url: str = path
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            headers = {}
            cached = _ETAG_CACHE.get(url)
            if cached:
                headers["If-None-Match"] = cached[0]

            # 翻页时 url 已经是完整地址,不能再带 params
            is_absolute = url.startswith("http")
            try:
                response = await self._client.get(
                    url, params=None if is_absolute else params, headers=headers
                )
            except httpx.TransportError as exc:
                # 网络层错误(连不上 / 超时 / TLS 失败)必须在这里转成 GitHubError,
                # 否则会原样漏成 500。而「连不上 GitHub」和「仓库不存在」是完全不同
                # 的两件事,用户需要知道卡在哪一层(实测栽过:容器连不上 api.github.com)。
                last_error = GitHubError(f"连接 GitHub 失败:{exc}")
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, self._max_backoff))
                    continue
                raise last_error from exc

            if response.status_code == 304:
                # 内容没变:返回缓存体,而不是空结果
                return (cached[1] if cached else None), response.headers
            if response.status_code in (200, 201):
                body = response.json()
                if new_etag := response.headers.get("ETag"):
                    _ETAG_CACHE[url] = (new_etag, body)
                return body, response.headers
            if response.status_code == 401:
                raise GitHubAuthError("GitHub token 无效或已过期")
            if response.status_code == 404:
                raise GitHubNotFound(f"GitHub 资源不存在: {url}")
            if response.status_code in (403, 429):
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining == "0" or response.status_code == 429:
                    delay = self._reset_delay(response.headers)
                    last_error = GitHubRateLimited(
                        f"触发 GitHub 速率限制,建议 {delay:.0f}s 后重试"
                    )
                    if attempt < self._max_retries and delay <= self._max_backoff:
                        await asyncio.sleep(delay)
                        continue
                    raise last_error
                raise GitHubError(f"GitHub 拒绝访问(403):{response.text[:200]}")
            if response.status_code >= 500:
                last_error = GitHubError(f"GitHub 服务端错误 {response.status_code}")
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, self._max_backoff))
                    continue
                raise last_error
            raise GitHubError(f"未预期的状态码 {response.status_code}")

        raise last_error or GitHubError("GitHub 调用失败")

    @staticmethod
    def _reset_delay(headers: httpx.Headers) -> float:
        reset = headers.get("X-RateLimit-Reset")
        if reset and str(reset).isdigit():
            return max(0.0, float(reset) - time.time())
        retry_after = headers.get("Retry-After")
        if retry_after:
            if str(retry_after).isdigit():
                return float(retry_after)
            try:
                when = parsedate_to_datetime(str(retry_after))
                return max(0.0, when.timestamp() - time.time())
            except (TypeError, ValueError):
                pass
        return 60.0

    async def _paginate(self, path: str, params: dict | None = None,
                        limit: int = 100) -> list[dict]:
        items: list[dict] = []
        url: str | None = path
        query: dict | None = {**(params or {}), "per_page": min(limit, 100)}
        while url and len(items) < limit:
            payload, headers = await self._get(url, query)
            if not isinstance(payload, list):
                break
            items.extend(payload)
            url = self.parse_link(headers.get("Link"))
            query = None
        return items[:limit]

    # ---------------------------------------------------------------- 业务接口

    async def list_issues(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        return await self._paginate(f"/repos/{owner}/{repo}/issues", {"state": state})

    async def list_pulls(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        return await self._paginate(f"/repos/{owner}/{repo}/pulls", {"state": state})

    async def pull_files(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files")

    async def list_workflow_runs(self, owner: str, repo: str) -> list[dict]:
        payload, _ = await self._get(f"/repos/{owner}/{repo}/actions/runs", {"per_page": 30})
        return (payload or {}).get("workflow_runs", [])

    async def get_repo(self, owner: str, repo: str) -> dict:
        """拉仓库元数据。

        必须用真实的 default_branch —— 之前建仓库行时用的是模型默认值 "main",
        而用户的仓库默认分支是 "master",于是同步回来的分支信息是错的。
        """
        payload, _ = await self._get(f"/repos/{owner}/{repo}")
        return payload or {}

    async def workflow_log(self, owner: str, repo: str, run_id: int) -> str:
        """拉取一次 CI 运行的日志。

        接口会 302 到签名地址并返回 **ZIP**,所以必须 follow_redirects 且解压。
        原实现只发了请求、没有任何调用方,等于这条链路根本不存在。
        """
        response = await self._client.get(
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs", follow_redirects=True
        )
        if response.status_code == 404:
            raise GitHubNotFound("CI 日志不存在或已过期")
        if response.status_code != 200:
            raise GitHubError(f"拉取 CI 日志失败:{response.status_code}")
        return extract_log_text(response.content)

    async def create_issue_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        response = await self._client.post(
            f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body}
        )
        if response.status_code not in (200, 201):
            raise GitHubError(f"发表评论失败:{response.status_code} {response.text[:200]}")
        return response.json()

    async def add_labels(self, owner: str, repo: str, number: int, labels: list[str]) -> Any:
        response = await self._client.post(
            f"/repos/{owner}/{repo}/issues/{number}/labels", json={"labels": labels}
        )
        if response.status_code not in (200, 201):
            raise GitHubError(f"添加标签失败:{response.status_code}")
        return response.json()

    async def update_issue(self, owner: str, repo: str, number: int, **fields: Any) -> dict:
        response = await self._client.patch(
            f"/repos/{owner}/{repo}/issues/{number}", json=fields
        )
        if response.status_code != 200:
            raise GitHubError(f"更新 Issue 失败:{response.status_code}")
        return response.json()