"""应用配置。

三个双模式开关(LLM_MODE / EMBED_MODE / DATA_SOURCE)是本项目的核心工程约束:
Demo 必须离线可跑、可单测,同时又能接真实上游。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # ---- LLM 双模式 ----
    llm_mode: Literal["mock", "openai"] = "mock"
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None

    # ---- Embedding 双模式 ----
    embed_mode: Literal["mock", "openai"] = "mock"
    embed_dim: int = 1024
    embed_model: str | None = None

    # ---- 研发数据来源 ----
    data_source: Literal["snapshot", "github"] = "snapshot"
    # 目标仓库(仅 github 模式需要),形如 acme/clowder-ai
    github_repo: str | None = None
    github_token: str | None = None
    github_api_base: str = "https://api.github.com"

    # ---- Agent 执行约束 ----
    context_budget: int = 8000
    max_agent_steps: int = 8
    max_replan: int = 2
    workflow_parallelism: int = 4

    # ---- 跨进程共享 ----
    # 空 = 退回进程内实现(单副本可用)。多副本部署必须配置。
    redis_url: str = ""
    # ETag 缓存存活时间。太长会看到过期数据,太短就白缓存了。
    etag_ttl_seconds: int = 900

    # ---- 跨域 ----
    # 前端(http://localhost:3000)与后端(8000)是**不同源**的,
    # 浏览器会拦下所有没有 CORS 头的响应 —— 页面会表现成"打不开/没数据"。
    # 注意:这里必须列具体来源,不能用 "*":一旦 allow_credentials=True,
    # 浏览器会直接拒绝通配符来源。
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ---- MCP 外部工具接入 ----
    # inprocess:进程内示例工具(默认,离线可跑) | stdio:真实 MCP server 子进程 + JSON-RPC
    mcp_transport: str = "inprocess"
    mcp_server_command: str = ""
    # 空格分隔的参数,例如 "-m app.mcp.servers.demo_server"
    mcp_server_args: str = "-m app.mcp.servers.demo_server"

    # ---- 自动周报 ----
    weekly_report_enabled: bool = True
    # 多久检查一次是否该出周报(秒)。默认 1 小时。
    weekly_report_check_seconds: int = 3600
    # 周报统计窗口天数
    weekly_report_days: int = 7

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in (self.cors_origins or "").split(",") if o.strip()]

    @property
    def mcp_server_args_list(self) -> list[str]:
        """把 MCP_SERVER_ARGS 按空格切开。command 留空时用当前解释器。"""
        return [part for part in (self.mcp_server_args or "").split(" ") if part]

    # ---- 评测 ----
    # RAGAS 评测器的地址。**它跑在独立容器里**:ragas 与本项目的 langchain 1.x 栈
    # 无法共存(新版导入即崩、老版强降 langchain 把主程序打挂),详见 services/ragas_eval/app.py。
    # 留空或连不上时,eval 会如实报告 unavailable,不编造指标。
    ragas_eval_url: str = ""

    # ---- 权限 ----
    # 形如 "member:tok1,maintainer:tok2"。留空 = 演示模式(无认证,客户端可自称角色),
    # /api/auth/me 会如实报告 enforced=false
    devflow_role_tokens: str = ""

    # ---- 基础设施 ----
    database_url: str = "postgresql+psycopg://devflow:devflow@postgres:5432/devflow"
    milvus_uri: str = "http://milvus:19530"
    milvus_collection: str = "devflow_chunks"
    snapshot_dir: str = "/app/data/snapshot"

    @property
    def snapshot_path(self) -> Path:
        return Path(self.snapshot_dir)

    @model_validator(mode="after")
    def _check_switch_consistency(self) -> "Settings":
        # mock 模式不校验(离线可用);
        # openai 模式缺项必须在启动就报错,而不是等第一次调用时抛一个看不懂的 401。
        if self.llm_mode == "openai":
            missing = [
                name
                for name in ("openai_base_url", "openai_api_key", "openai_model")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    "LLM_MODE=openai 缺少必填项: " + ", ".join(m.upper() for m in missing)
                )
        if self.embed_mode == "openai" and not self.embed_model:
            raise ValueError("EMBED_MODE=openai 缺少: EMBED_MODEL")
        # DATA_SOURCE=github 时故意不校验 token:
        # 静默回退到快照会让人把假数据当真实结论,所以让工具层显式报「未配置 token」,
        # 而不是在启动阶段替用户决定用哪种数据。
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()