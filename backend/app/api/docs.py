"""离线可用的 API 文档页(Swagger UI + ReDoc)。

**为什么不用 FastAPI 的默认 `/docs`**:它从 `cdn.jsdelivr.net` 拉 Swagger 的 JS/CSS。
国内网络下这个 CDN 经常连不上或极慢,页面就是一片空白 —— 用户看到的现象是
「文档打不开」,但服务端一切正常,很难查。所以把静态资源**放进仓库**、由后端自己托管。

另外 FastAPI 默认 HTML 里引用了 `SwaggerUIBundle.SwaggerUIStandalonePreset`,
而那个 preset 其实在**另一个文件**里(`swagger-ui-standalone-preset.js`)——
只替换 js_url 而不加载它会直接白屏。这里的 HTML 显式加载两个脚本,
把 preset 正确接上。
"""

from __future__ import annotations

from pathlib import Path

# 本文件在 app/api/ 下,静态资源在 app/static/(所以取 parents[1])
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
SWAGGER_DIR = STATIC_DIR / "swagger"

SWAGGER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DevFlow AI · API 文档</title>
  <link rel="stylesheet" href="/static/swagger/swagger-ui.css">
  <link rel="stylesheet" href="/static/swagger/devflow-docs.css">
  <link rel="icon" href="/static/swagger/favicon-32x32.png">
  <style>body { margin: 0; }</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="/static/swagger/swagger-ui-bundle.js"></script>
<script src="/static/swagger/swagger-ui-standalone-preset.js"></script>
<script>
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
    plugins: [SwaggerUIBundle.plugins.DownloadUrl],
  });
</script>
</body>
</html>
"""

REDOC_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DevFlow AI · API 文档(ReDoc)</title>
  <style>body { margin: 0; padding: 0; }</style>
</head>
<body>
<redoc spec-url="/openapi.json"></redoc>
<script src="/static/swagger/redoc.standalone.js"></script>
</body>
</html>
"""