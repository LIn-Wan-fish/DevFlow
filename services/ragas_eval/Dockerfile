FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# 构建时网络环境差异很大:国内环境直连 pypi.org 常常读超时(实测踩到)。
# 默认走官方源,需要时用 --build-arg PIP_INDEX_URL=<镜像源> 覆盖,
# 也可以直接设环境变量 PIP_INDEX_URL 让 compose 透传。
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir \
      --index-url "$PIP_INDEX_URL" \
      ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} \
      -r requirements.txt
COPY app.py ./

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]