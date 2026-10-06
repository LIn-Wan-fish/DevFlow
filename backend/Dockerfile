FROM docker.m.daocloud.io/library/python:3.12-slim

# 容器内不装编译工具链:依赖全部走 wheel。装不上说明该依赖在 3.12 上没 wheel,
# 这是要停下来问人的信号,不要在这里加 build-essential 硬扛。
RUN pip install --no-cache-dir -U pip uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-install-project

# 合并 CA:certifi 公共根 + certs/extra-ca/ 下的额外根(可为空)。
# 本机启用 GitHub 加速器时,把它的根证书放进 extra-ca 才能连通;
# 目录为空时结果等同纯 certifi,不影响默认行为。
COPY certs/ /opt/certs/
RUN python /opt/certs/build_bundle.py
ENV SSL_CERT_FILE=/opt/combined-ca.pem

COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]