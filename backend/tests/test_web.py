"""浏览器侧才能暴露的问题:跨域与文档页的外部依赖。

这两类问题**服务端 httpx 测试全都发现不了** ——
CORS 是浏览器强制的,CDN 依赖只有真的在浏览器里打开才会暴露。
所以必须专门盯住,否则会悄悄坏掉。
"""

from __future__ import annotations

import re

FRONTEND = "http://localhost:3000"


def test_跨域预检必须通过(client):
    """没有 CORS 中间件时这里的返回是 405,浏览器会因此拦掉所有请求。"""
    response = client.options(
        "/api/repos",
        headers={"Origin": FRONTEND, "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_带_Origin_的普通响应也必须带_cors_头(client):
    """预检过了还不够:实际响应上也要有 allow-origin,否则浏览器读不到内容。"""
    response = client.get("/api/repos", headers={"Origin": FRONTEND})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == FRONTEND


def test_写接口的预检也要过(client):
    """POST + JSON 一定会触发预检 —— SSE 对话就属于这类,不过就完全用不了。"""
    response = client.options(
        "/api/chat/stream",
        headers={"Origin": FRONTEND, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_未知来源不被放行(client):
    """允许列表不能退化成通配符。"""
    response = client.get("/api/repos", headers={"Origin": "http://evil.example.com"})
    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"


# --------------------------------------------------------------------------- 文档页


def test_文档页不依赖任何外部_cdn(client):
    """回归:FastAPI 默认的 /docs 从 cdn.jsdelivr.net 拉 JS/CSS。

    国内网络下这个 CDN 经常连不上,页面白屏 —— 而服务端一切正常,极难排查。
    所以静态资源随仓库分发,由后端自己托管。
    """
    html = client.get("/docs").text
    assert "cdn.jsdelivr.net" not in html
    # 页面里出现的每个 <script src> 都必须是本地路径,不能有外站
    srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    assert srcs, "页面必须真的加载脚本"
    assert all(s.startswith("/static/") for s in srcs), srcs
    assert "/static/swagger/swagger-ui-bundle.js" in html
    assert "/static/swagger/swagger-ui.css" in html


def test_文档页把_standalone_preset_也加载了(client):
    """FastAPI 默认 HTML 会引用 SwaggerUIBundle.SwaggerUIStandalonePreset,
    但那个 preset 在**另一个文件**里 —— 只换 js_url 不加载它会直接白屏。"""
    html = client.get("/docs").text
    assert "/static/swagger/swagger-ui-standalone-preset.js" in html
    assert "SwaggerUIStandalonePreset" in html


def test_文档静态资源可访问(client):
    for path in ("/static/swagger/swagger-ui.css",
                 "/static/swagger/swagger-ui-bundle.js",
                 "/static/swagger/swagger-ui-standalone-preset.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 1000, path


def test_redoc_也不依赖外部_cdn(client):
    html = client.get("/redoc").text
    assert "cdn.jsdelivr.net" not in html
    assert "/static/swagger/redoc.standalone.js" in html