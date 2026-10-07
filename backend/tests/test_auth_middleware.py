"""令牌认证的默认拒绝边界。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings

TOKENS = "viewer:tok-v,member:tok-m,maintainer:tok-t"


@pytest.fixture
def secured(monkeypatch):
    """进入令牌认证模式。**必须新建 client** —— 设置是在请求时读的,但为了
    确保中间件与依赖都看到新配置,重新构造最稳。"""
    monkeypatch.setattr(settings, "devflow_role_tokens", TOKENS)
    from app.main import app

    with TestClient(app) as client:
        yield client


H_VIEWER = {"X-DevFlow-Role-Token": "tok-v"}
H_MEMBER = {"X-DevFlow-Role-Token": "tok-m"}


def test_不带令牌的读接口被拒(secured):
    """回归:令牌校验原先只挂在写接口上,读接口(仓库、审计)**完全敞开** ——
    无效令牌甚至不带令牌都能读到数据。改成中间件默认拒绝。"""
    assert secured.get("/api/repos").status_code == 401
    assert secured.get("/api/drafts").status_code == 401
    assert secured.get("/api/drafts/audit").status_code == 401


def test_无效令牌被拒(secured):
    assert secured.get("/api/repos", headers={"X-DevFlow-Role-Token": "bad"}).status_code == 401


def test_带有效令牌可读(secured):
    assert secured.get("/api/repos", headers=H_VIEWER).status_code == 200


def test_伪造角色名完全无效(secured):
    """这套机制**存在的理由**:演示模式下 `X-DevFlow-Role: maintainer` 就能冒充角色。
    令牌模式下它必须一点作用都没有。"""
    r = secured.get("/api/repos", headers={"X-DevFlow-Role": "maintainer"})
    assert r.status_code == 401, "自称角色不该被接受"


def test_Bearer_令牌也行(secured):
    r = secured.get("/api/repos", headers={"Authorization": "Bearer tok-v"})
    assert r.status_code == 200


def test_健康检查与认证模式免认证(secured):
    """探活和"我是什么模式"必须免认证 —— 否则负载均衡和前端都无从判断。"""
    assert secured.get("/api/health").status_code == 200
    mode = secured.get("/api/auth/mode")
    assert mode.status_code == 200
    assert mode.json()["enforced"] is True


def test_跨域预检免认证(secured):
    """预检本身不带凭据,拦掉会让浏览器以为整个跨域不可用。"""
    r = secured.options("/api/repos", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200


def test_viewer_不能写(secured):
    """关键是**写操作不会成功**,而不是某个特定状态码。

    草稿不存在时返回 404 而不是 403 是刻意的:先查草稿,且用 404 避免
    把「这个 id 存在但你没权限」泄漏给探测者。真正的越权(草稿确实存在)
    由 scripts/verify_prod.py 端到端验证 —— 那边有真草稿。
    """
    r = secured.post("/api/drafts/999999/confirm", headers=H_VIEWER)
    assert r.status_code in (403, 404), f"viewer 不该能写,却得到 {r.status_code}"


def test_演示模式下一切照旧(monkeypatch):
    """没配令牌时不能把功能拦死 —— 单机 Demo 要能开箱即用。"""
    monkeypatch.setattr(settings, "devflow_role_tokens", "")
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/repos").status_code == 200
        assert client.get("/api/auth/mode").json()["enforced"] is False
