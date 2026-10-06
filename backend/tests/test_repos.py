"""添加仓库:解析、幂等、失败不留空壳。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import models as m
from app.github import client as gh_client
from app.github import provider
from app.repos import service


@pytest.mark.parametrize("raw,expected", [
    ("owner/name", ("owner", "name")),
    ("  owner/name  ", ("owner", "name")),
    ("https://github.com/owner/name", ("owner", "name")),
    ("https://github.com/owner/name.git", ("owner", "name")),
    ("http://www.github.com/owner/name/", ("owner", "name")),
    ("LIn-Wan-fish/DevFlow", ("LIn-Wan-fish", "DevFlow")),
])
def test_仓库名解析(raw, expected):
    """也接受直接粘贴仓库地址 —— 从浏览器地址栏复制的就是这种。"""
    assert service.parse_full_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "只有名字", "a/b/c", "owner/", "/name", "own er/name", "owner/na me"])
def test_非法仓库名被拒绝(raw):
    with pytest.raises(service.RepoAddError):
        service.parse_full_name(raw)


async def test_没有令牌时给出可读原因(db_with_snapshot, monkeypatch):
    from app.github.client import GitHubNotConfigured

    def boom(*_a, **_k):
        raise GitHubNotConfigured()

    monkeypatch.setattr(service, "require_client", boom)
    with pytest.raises(service.RepoAddError) as exc:
        await service.add_repo(db_with_snapshot, "someone/somerepo")
    assert "GITHUB_TOKEN" in exc.value.detail
    assert exc.value.status == 400


async def test_仓库不存在时不留空壳(db_with_snapshot, monkeypatch):
    """先确认可见再建行 —— 否则界面上会多出一个永远为空的幽灵项目。"""
    from app.github.client import GitHubNotFound

    class FakeClient:
        async def get_repo(self, owner, name):
            raise GitHubNotFound("不存在")

    monkeypatch.setattr(service, "require_client", lambda **_k: FakeClient())
    before = db_with_snapshot.scalar(select(m.Repo.id).where(m.Repo.owner == "ghost"))
    assert before is None

    with pytest.raises(service.RepoAddError) as exc:
        await service.add_repo(db_with_snapshot, "ghost/nothing")
    assert exc.value.status == 404

    after = db_with_snapshot.scalar(select(m.Repo).where(m.Repo.owner == "ghost"))
    assert after is None, "失败后不该留下仓库行"


async def test_添加成功并同步(db_with_snapshot, monkeypatch):
    class FakeClient:
        async def get_repo(self, owner, name):
            return {"default_branch": "develop"}

    synced = {}

    async def fake_sync(db, repo_id, **kwargs):
        synced["repo_id"] = repo_id
        synced["explicit"] = kwargs.get("explicit")
        return {"issues": 3}

    monkeypatch.setattr(service, "require_client", lambda **_k: FakeClient())
    monkeypatch.setattr(service, "sync_repo", fake_sync)

    repo, counts = await service.add_repo(db_with_snapshot, "new/project")
    assert repo.full_name == "new/project"
    assert repo.is_github is True
    assert repo.default_branch == "develop", "默认分支要按 GitHub 的真实值存,不能写死 main"
    assert counts == {"issues": 3}
    # 显式添加必须在快照模式下也能用,不能要求先切 DATA_SOURCE
    assert synced["explicit"] is True


async def test_重复添加是幂等的(db_with_snapshot, monkeypatch):
    class FakeClient:
        async def get_repo(self, owner, name):
            return {"default_branch": "main"}

    monkeypatch.setattr(service, "require_client", lambda **_k: FakeClient())

    async def fake_sync(db, repo_id, **kwargs):
        return {}

    monkeypatch.setattr(service, "sync_repo", fake_sync)

    first, _ = await service.add_repo(db_with_snapshot, "dup/repo")
    second, meta = await service.add_repo(db_with_snapshot, "dup/repo")
    assert first.id == second.id
    assert meta.get("already_exists") is True


async def test_快照仓库拒绝同步(db_with_snapshot, repo_id):
    """快照仓库没有上游,如实说明而不是假装同步成功。"""
    repo = db_with_snapshot.get(m.Repo, repo_id)
    assert repo is not None and repo.is_github is False
    with pytest.raises(service.RepoAddError) as exc:
        await service.resync(db_with_snapshot, repo)
    assert "快照" in exc.value.detail


# --------------------------------------------------------------------------- API


def test_添加接口_格式错误返回_400(client):
    r = client.post("/api/repos", json={"full_name": "不是仓库名"})
    assert r.status_code == 400
    assert "owner/name" in r.json()["detail"]


def test_添加接口_快照仓库同步返回_400(client):
    r = client.post("/api/repos/1/sync")
    assert r.status_code == 400
    assert "快照" in r.json()["detail"]


def test_同步不存在的仓库返回_404(client):
    assert client.post("/api/repos/999999/sync").status_code == 404
